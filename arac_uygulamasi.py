import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import gspread
from google.oauth2.service_account import Credentials
import os
import json
import re # Otomatik temizleme için

# --- 1. UYGULA AYARLARI VE GOOGLE SHEETS BAĞLANTISI ---

# Masraf kategorilerimiz
KATEGORILER_TUMU = [
    'Yakıt', 'Köprü Otoyol', 'Trafik Cezaları', 'Tamir-Servis', 
    'Periyodik Bakım', 'Muayene', 'Lastik', 'Aksesuar', 
    'Vergiler', 'Otopark', 'Araç Yıkama', 'Sigorta-Kasko'
]
KATEGORILER_DIGER = [k for k in KATEGORILER_TUMU if k != 'Yakıt']
KM_GEREKEN_KATEGORILER = ['Periyodik Bakım', 'Tamir-Servis', 'Lastik', 'Muayene']

# Google Sheets'e bağlanmak için gerekli yetki kapsamları
SCOPES = [
    "https.www.googleapis.com/auth/spreadsheets",
    "https.www.googleapis.com/auth/drive"
]

# Google E-Tablonuzun tam adı
GOOGLE_SHEET_NAME = "Arac Masraflari"
# E-Tablonuzdaki çalışma sayfasının adı
WORKSHEET_NAME = "Veriler"

# Gerekli sütunlar (E-Tablonuzdaki ile aynı olmalı)
REQUIRED_COLUMNS = [
    "Tarih", "KM Sayacı", "Masraf Türü", "Tutar", "Açıklama", 
    "Taksit Sayısı", "Litre", "Dolum Türü"
]

# Sayfa ayarları
st.set_page_config(
    page_title="Araç Masraf Takip Uygulaması",
    page_icon="🚗",
    layout="wide"
)
st.title("🚗 Araç Masraf Takip Uygulaması")

#
# --- BAĞLANTI KODU (DEĞİŞİKLİK YOK) ---
#
@st.cache_resource(ttl=60)
def connect_to_sheet():
    """Google Sheets'e bağlanır ve çalışma sayfasını döndürür."""
    
    gc = None
    
    try:
        # DENE: Streamlit Cloud (st.secrets) yolunu dene
        if st.secrets.get("GOOGLE_SHEETS_CREDENTIALS"):
            try:
                creds_dict = st.secrets["GOOGLE_SHEETS_CREDENTIALS"]
                creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
                gc = gspread.authorize(creds)
                
            except Exception as e:
                st.error(f"Secrets ile kimlik doğrulama hatası: {e}")
                st.info("Secrets (TOML) formatını doğru girdiğinizden emin misiniz?")
                st.stop()
        else:
            raise st.errors.StreamlitSecretNotFoundError("Anahtar bulunamadı, yerel varsayılıyor.")

    except st.errors.StreamlitSecretNotFoundError:
        # HATA: Secrets dosyası bulunamadı (Yani YERELDE çalışıyoruz)
        LOCAL_CREDS_PATH = "google_credentials.json"
        
        if not os.path.exists(LOCAL_CREDS_PATH):
            st.error("Yerel 'google_credentials.json' dosyası bulunamadı.")
            st.info(f"'{os.path.abspath(LOCAL_CREDS_PATH)}' konumuna dosyayı koyduğunuzdan emin olun.")
            st.stop()
        
        try:
            creds = Credentials.from_service_account_file(LOCAL_CREDS_PATH, scopes=SCOPES)
            gc = gspread.authorize(creds)
        except Exception as e:
            st.error(f"Yerel 'google_credentials.json' dosyası ile kimlik doğrulama hatası: {e}")
            st.stop()
    except Exception as e:
        st.error(f"Kimlik doğrulama sırasında genel hata: {e}")
        st.stop()

    # Adım 2: E-Tabloya Bağlan
    if gc is None:
        st.error("Kimlik doğrulama istemcisi (gc) oluşturulamadı.")
        st.stop()
        
    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        worksheet = sh.worksheet(WORKSHEET_NAME)
        return worksheet
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"E-Tablo Bulunamadı: '{GOOGLE_SHEET_NAME}' adlı Google E-Tablosu bulunamadı.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Çalışma Sayfası Bulunamadı: '{WORKSHEET_NAME}' adlı çalışma sayfası bulunamadı.")
        st.stop()
    except gspread.exceptions.APIError as e:
        st.error(f"Google API Hatası (Yetki Hatası): {e}")
        st.info(f"'{GOOGLE_SHEET_NAME}' adlı E-Tabloyu, 'client_email' adresiyle 'Düzenleyici' olarak paylaştığınıza emin misiniz?")
        st.stop()
    except Exception as e:
        st.error(f"E-Tabloya bağlanırken bilinmeyen bir hata oluştu: {e}")
        st.stop()

def create_empty_dataframe():
    """Gerekli sütunlara sahip boş bir DataFrame oluşturur."""
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    df['Tarih'] = pd.to_datetime(df['Tarih'])
    df['KM Sayacı'] = pd.to_numeric(df['KM Sayacı'])
    df['Tutar'] = pd.to_numeric(df['Tutar'])
    df['Taksit Sayısı'] = pd.to_numeric(df['Taksit Sayısı'])
    df['Litre'] = pd.to_numeric(df['Litre'])
    return df

#
# --- GÜNCELLENMİŞ FONKSİYON ---
#
def load_data():
    """Google Sheets'ten veriyi yükler ve DataFrame'e dönüştürür."""
    
    worksheet = connect_to_sheet() 
    
    if worksheet is None:
        return create_empty_dataframe()
        
    try:
        data = worksheet.get_all_values()
        
        if len(data) < 2: 
            return create_empty_dataframe()
        
        headers = data[0]
        if headers != REQUIRED_COLUMNS:
            st.error(f"E-Tablo başlıkları hatalı! Gerekli: {REQUIRED_COLUMNS}")
            return create_empty_dataframe()
            
        df = pd.DataFrame(data[1:], columns=headers)
        
        df['Tarih'] = pd.to_datetime(df['Tarih'], errors='coerce')
        
        numeric_cols = ['KM Sayacı', 'Tutar', 'Taksit Sayısı', 'Litre']
        for col in numeric_cols:
            df[col] = df[col].str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        df['Taksit Sayısı'] = df['Taksit Sayısı'].apply(lambda x: 1 if x < 1 else int(x))
        
        df = df.dropna(subset=['Tarih'])
        return df
        
    except Exception as e:
        st.error(f"Veri yüklenirken hata oluştu: {e}")
        return create_empty_dataframe()

#
# --- GÜNCELLENMİŞ FONKSİYON ---
#
def save_data(df):
    """DataFrame'i Google Sheets'e kaydeder VE session_state'i günceller."""
    
    worksheet = connect_to_sheet()
    
    if worksheet is None:
        st.error("Kaydedilecek yer bulunamadı (Worksheet bağlantısı yok).")
        return
        
    try:
        df_sorted = df.sort_values(by=["Tarih", "KM Sayacı"], ascending=True)
        
        df_sorted['Tarih'] = df_sorted['Tarih'].dt.strftime('%Y-%m-%d')
        df_sorted['Tutar'] = df_sorted['Tutar'].apply(lambda x: f"{x:.2f}".replace('.', ','))
        df_sorted['Litre'] = df_sorted['Litre'].apply(lambda x: f"{x:.2f}".replace('.', ','))

        df_sorted_str = df_sorted.fillna('').astype(str)
        
        worksheet.clear()
        worksheet.update([REQUIRED_COLUMNS] + df_sorted_str.values.tolist(), value_input_option='USER_ENTERED')
        
        # Hafızayı (session_state) GÜNCELLE
        st.session_state.df_main = df_sorted.copy()
        
        st.cache_resource.clear() 
    except Exception as e:
        st.error(f"Veri kaydedilirken hata oluştu: {e}")

#
# --- Ana Uygulama Akışı (SESSION STATE EKLENDİ) ---
#
if "df_main" not in st.session_state:
    st.session_state.df_main = load_data() 

df_main = st.session_state.df_main

# --- 2. SEKMELERİ OLUŞTURMA (5 SEKMELİ YAPI) ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "⛽ Yakıt Masrafı Gir",
    "🛒 Diğer Masrafları Gir", 
    "📊 Yakıt Analizi", 
    "💳 Genel Masraf Analizi", 
    "✏️ Veri Yönetimi"
])


#
# --- 3. SEKME 1: YAKIT MASRAFI GİRME (st.rerun() KALDIRILDI) ---
#
with tab1:
    st.header("Yeni Yakıt Alımı Kaydı")
    
    with st.form("yakit_formu", clear_on_submit=True):
        st.subheader("Yakıt Detayları")
        col1, col2 = st.columns(2)
        with col1:
            tarih_input = st.date_input("Tarih", value=datetime.now())
        with col2:
            km_input = st.number_input("Aracın Güncel Kilometresi", min_value=0, step=1, value=int(df_main['KM Sayacı'].max()) if not df_main.empty else 0)
        
        col3, col4 = st.columns(2)
        with col3:
            yakit_tutar_input = st.number_input("Toplam Yakıt Tutarı (TL)", min_value=0.0, format="%.2f")
        with col4:
            yakit_litre_input = st.number_input("Alınan Yakıt (Litre)", min_value=0.0, format="%.2f")
        
        dolum_turu_input = st.radio("Depo Dolum Türü", ['Full Dolum', 'Kısmi Dolum'], index=0)
        aciklama_input = st.text_input("Açıklama (Opsiyonel, Örn: Shell V-Power)", "Yakıt Alımı")

        submitted = st.form_submit_button("Yakıt Kaydını Ekle")
        
        if submitted:
            if km_input == 0 or yakit_tutar_input == 0 or yakit_litre_input == 0:
                st.error("Lütfen KM, Tutar ve Litre alanlarını doldurun.")
            elif not df_main.empty and km_input < df_main['KM Sayacı'].max():
                 st.error(f"Girdiğiniz KM ({km_input}), son kayıtlı KM'den ({int(df_main['KM Sayacı'].max())}) düşük olamaz.")
            else:
                yeni_kayit = {
                    "Tarih": pd.to_datetime(tarih_input),
                    "KM Sayacı": km_input,
                    "Masraf Türü": "Yakıt",
                    "Tutar": yakit_tutar_input,
                    "Açıklama": aciklama_input,
                    "Taksit Sayısı": 1,
                    "Litre": yakit_litre_input,
                    "Dolum Türü": dolum_turu_input
                }
                
                df_yeni = pd.DataFrame([yeni_kayit])
                df_main_guncel = pd.concat([df_main, df_yeni], ignore_index=True)
                save_data(df_main_guncel) 
                st.success("Yakıt masrafı başarıyla kaydedildi!")
                # st.rerun() KALDIRILDI! Form zaten kendi kendini temizliyor.

#
# --- 4. SEKME 2: DİĞER MASRAFLARI GİRME (st.rerun() KALDIRILDI + MANUEL TEMİZLEME EKLENDİ) ---
#
with tab2:
    st.header("Yeni Masraf Kaydı (Yakıt Dışı)")

    st.subheader("Masraf Detayları")
    
    # Widget'lara 'key' (anahtar) ekledik
    tarih_input_d = st.date_input("Tarih", value=datetime.now(), key="diger_tarih")
    masraf_turu_input_d = st.selectbox("Masraf Türünü Seçin", options=KATEGORILER_DIGER, key="diger_tur") 

    km_input_d = None
    if masraf_turu_input_d in KM_GEREKEN_KATEGORILER:
        km_input_d = st.number_input(
            "Aracın Güncel Kilometresi", 
            min_value=0, 
            step=1, 
            value=int(df_main['KM Sayacı'].max()) if not df_main.empty else 0,
            key="diger_km" # Buna da key verelim
        )
        st.info(f"'{masraf_turu_input_d}' için KM girmek, bakım ve parça ömrü takibi için önemlidir.")
    
    col3, col4 = st.columns(2)
    with col3:
        diger_tutar_input = st.number_input("Toplam Masraf Tutarı (TL)", min_value=0.0, format="%.2f", key="diger_tutar")
    with col4:
        taksit_input = st.number_input("Taksit Sayısı", min_value=1, value=1, step=1, key="diger_taksit")
    
    aciklama_input_d = st.text_input("Masraf Açıklaması (Örn: 10.000km bakımı, İspark Otopark, Kasko Poliçesi)", key="diger_aciklama")

    submitted_d = st.button("Masrafı Kaydet")
    
    if submitted_d:
        # Girdileri kontrol et
        is_km_required = masraf_turu_input_d in KM_GEREKEN_KATEGORILER
        
        # KM'yi state'den oku (eğer görünürse)
        km_degeri = st.session_state.diger_km if is_km_required else None
        
        if is_km_required and (km_degeri is None or km_degeri == 0):
            st.error(f"'{masraf_turu_input_d}' için KM sayacı girmek zorunludur.")
        elif st.session_state.diger_tutar == 0:
             st.error("Lütfen masraf tutarını girin.")
        elif not st.session_state.diger_aciklama:
            st.error("Lütfen bir açıklama girin (Örn: Otopark, Bakım vb.)")
        else:
            # KM Gerekmiyorsa, son bilinen KM'yi otomatik ata
            kaydedilecek_km = 0
            if km_degeri is not None:
                # KM girildiyse ve gerekliyse, KM'nin geriye gitmediğini kontrol et
                if not df_main.empty and km_degeri < df_main['KM Sayacı'].max():
                    st.error(f"Girdiğiniz KM ({km_degeri}), son kayıtlı KM'den ({int(df_main['KM Sayacı'].max())}) düşük olamaz.")
                    st.stop() # Kaydı durdur
                kaydedilecek_km = km_degeri
            else:
                # KM girilmediyse (çünkü sorulmadı), son bilinen KM'yi al
                kaydedilecek_km = int(df_main['KM Sayacı'].max()) if not df_main.empty else 0
            
            yeni_kayit = {
                "Tarih": pd.to_datetime(st.session_state.diger_tarih),
                "KM Sayacı": kaydedilecek_km,
                "Masraf Türü": st.session_state.diger_tur,
                "Tutar": st.session_state.diger_tutar,
                "Açıklama": st.session_state.diger_aciklama,
                "Taksit Sayısı": st.session_state.diger_taksit,
                "Litre": 0,
                "Dolum Türü": ""
            }
            
            df_yeni = pd.DataFrame([yeni_kayit])
            df_main_guncel = pd.concat([df_main, df_yeni], ignore_index=True)
            save_data(df_main_guncel) 
            st.success(f"'{st.session_state.diger_tur}' masrafı başarıyla kaydedildi!")
            
            # --- MANUEL ALAN TEMİZLEME (st.rerun() yerine) ---
            st.session_state.diger_tutar = 0.0
            st.session_state.diger_aciklama = ""
            st.session_state.diger_taksit = 1
            # st.rerun() KALDIRILDI!


#
# --- 5. SEKME 3: YAKIT ANALİZİ (MANTIK HATASI DÜZELTİLDİ) ---
#
with tab3:
    st.header("Yakıt Tüketim Analizi")
    
    yakit_df = df_main[df_main["Masraf Türü"] == 'Yakıt'].sort_values(by="KM Sayacı").reset_index(drop=True)

    if len(yakit_df) < 2:
        st.info("Yakıt tüketim analizi için en az 2 'Yakıt' kaydı gereklidir.")
    else:
        
        # --- "TRIP" (FULL-TO-FULL) HESAPLAMASI (Metrikler için Öne Alındı) ---
        full_dolum_indeksleri = yakit_df[yakit_df["Dolum Türü"] == 'Full Dolum'].index.tolist()
        trip_raporlari = []

        genel_ortalama_lt_100km = 0
        genel_ortalama_tl_km = 0
        trip_raporlari_df = pd.DataFrame() # Boş DF

        if len(full_dolum_indeksleri) < 2:
            st.warning("Genel ortalamaların hesaplanması için en az 2 'Full Dolum' kaydı gereklidir.")
        else:
            for i in range(len(full_dolum_indeksleri) - 1):
                start_index = full_dolum_indeksleri[i]
                end_index = full_dolum_indeksleri[i+1]
                
                trip_df = yakit_df.iloc[start_index : end_index + 1]
                
                baslangic_km = trip_df["KM Sayacı"].iloc[0]
                bitis_km = trip_df["KM Sayacı"].iloc[-1]
                gidilen_km = bitis_km - baslangic_km
                
                tuketilen_litre = trip_df["Litre"].iloc[1:].sum()
                harcanan_para = trip_df["Tutar"].iloc[1:].sum()
                
                if gidilen_km > 0:
                    lt_100km = (tuketilen_litre / gidilen_km) * 100
                    tl_km = harcanan_para / gidilen_km
                    
                    trip_raporlari.append({
                        "Başlangıç KM": int(baslangic_km),
                        "Bitiş KM": int(bitis_km),
                        "Gidilen KM": int(gidilen_km),
                        "Tüketilen Litre": float(tuketilen_litre),
                        "Harcanan Para (Trip)": float(harcanan_para),
                        "L/100km (Ort.)": float(lt_100km),
                        "TL/km (Ort.)": float(tl_km)
                    })
            
            if trip_raporlari:
                trip_raporlari_df = pd.DataFrame(trip_raporlari)
                
                # --- YENİ "GENEL BAKIŞ" HESAPLAMASI (Sadece Trip'lere göre) ---
                toplam_trip_km = trip_raporlari_df['Gidilen KM'].sum()
                toplam_trip_litre = trip_raporlari_df['Tüketilen Litre'].sum()
                toplam_trip_para = trip_raporlari_df['Harcanan Para (Trip)'].sum()
                
                if toplam_trip_km > 0:
                    genel_ortalama_lt_100km = (toplam_trip_litre / toplam_trip_km) * 100
                    genel_ortalama_tl_km = toplam_trip_para / toplam_trip_km

        # --- "GENEL BAKIŞ" (Tüm Zamanlar) - (DÜZENLENDİ) ---
        st.subheader("Genel Bakış (Tamamlanmış 'Trip' Ortalamaları)")
        st.info("Bu ortalamalar, sadece 'Full Dolum'dan 'Full Dolum'a tamamlanmış seyahatlerin verilerini yansıtır. 'Kısmi Dolum'lar bu ortalamayı anlık olarak etkilemez.")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Genel Ortalama (L/100km)", f"{genel_ortalama_lt_100km:.2f}")
        col2.metric("Genel Ortalama (TL/km)", f"{genel_ortalama_tl_km:.2f}")
        
        toplam_gidilen_km_tum_zamanlar = yakit_df["KM Sayacı"].iloc[-1] - yakit_df["KM Sayacı"].iloc[0]
        col3.metric("Toplam Gidilen KM (Tüm Kayıtlar)", f"{toplam_gidilen_km_tum_zamanlar:,.0f}")
        col4.metric("Toplam Yakıt Harcaması (Tüm Kayıtlar)", f"{yakit_df['Tutar'].sum():,.2f} TL")

        st.divider()

        # --- "TRIP" (FULL-TO-FULL) TABLOSU ---
        st.subheader("Dolum Periyotlarına Göre Tüketim Analizi (Full-to-Full)")
        if not trip_raporlari_df.empty:
            # Raporlama için formatlanmış DataFrame
            trip_raporlari_display_df = trip_raporlari_df.copy()
            trip_raporlari_display_df['Tüketilen Litre'] = trip_raporlari_display_df['Tüketilen Litre'].map('{:,.2f}'.format)
            trip_raporlari_display_df['L/100km (Ort.)'] = trip_raporlari_display_df['L/100km (Ort.)'].map('{:,.2f}'.format)
            trip_raporlari_display_df['TL/km (Ort.)'] = trip_raporlari_display_df['TL/km (Ort.)'].map('{:,.2f}'.format)
            
            st.dataframe(
                trip_raporlari_display_df.drop(columns=['Harcanan Para (Trip)']), # Ham para verisini gösterme
                hide_index=True, 
                use_container_width=True
            )
        else:
            st.warning("Henüz tamamlanmış bir 'Full-to-Full' periyodu yok.")


        st.divider()
        
        # --- AYLIK ÖZET TABLOSU (DÜZENLENDİ - Ortalamalar Kaldırıldı) ---
        st.subheader("Aylık Yakıt Gider Özeti")
        st.info("Bu tablo, her ay yakıta ne kadar para harcadığınızı ve toplam kaç litre yakıt aldığınızı gösterir.")
        
        if not yakit_df.empty:
            yakit_aylik = yakit_df.set_index('Tarih').copy()
            
            aylik_ozet = yakit_aylik.resample('ME').agg(
                Toplam_Harcanan_Para_TL=('Tutar', 'sum'),
                Toplam_Alınan_Litre=('Litre', 'sum')
            )
            
            # Sadece harcama olan ayları göster
            aylik_ozet = aylik_ozet[aylik_ozet['Toplam_Harcanan_Para_TL'] > 0]
            
            aylik_ozet = aylik_ozet.rename(columns={
                'Toplam_Harcanan_Para_TL': 'Toplam Harcanan Para (TL)',
                'Toplam_Alınan_Litre': 'Toplam Alınan Litre',
            })
            
            aylik_ozet.index = aylik_ozet.index.strftime('%Y-%B')
            st.dataframe(aylik_ozet.sort_index(ascending=False).style.format("{:,.2f}"), use_container_width=True)


# --- 6. SEKME 4: GENEL MASRAF ANALİZİ ---
with tab4:
    st.header("Genel Masraf Analizi")

    if df_main.empty:
        st.info("Analiz için henüz bir masraf kaydı girmediniz.")
    else:
        odeme_kayitlari = []
        for _, row in df_main.iterrows():
            if row['Taksit Sayısı'] == 0: continue 
            taksit_tutari = row['Tutar'] / row['Taksit Sayısı']
            for i in range(int(row['Taksit Sayısı'])):
                odeme_tarihi = row['Tarih'] + relativedelta(months=i)
                odeme_kayitlari.append({
                    "Ödeme Tarihi": odeme_tarihi,
                    "Kategori": row['Masraf Türü'],
                    "Ödeme Tutarı": taksit_tutari
                })
        
        odeme_df = pd.DataFrame(odeme_kayitlari)
        
        bugun = datetime.now()
        bu_ay_baslangic = bugun.replace(day=1, hour=0, minute=0, second=0)
        
        bu_ayki_odemeler = pd.DataFrame()
        if not odeme_df.empty: 
            bu_ayki_odemeler = odeme_df[
                (odeme_df['Ödeme Tarihi'] >= pd.to_datetime(bu_ay_baslangic)) &
                (odeme_df['Ödeme Tarihi'] < pd.to_datetime(bu_ay_baslangic + relativedelta(months=1)))
            ]
        
        toplam_harcama = df_main['Tutar'].sum()
        bu_ayki_toplam_odeme = bu_ayki_odemeler['Ödeme Tutarı'].sum() if not bu_ayki_odemeler.empty else 0

        col1, col2 = st.columns(2)
        col1.metric("Tüm Zamanlar Toplam Harcama", f"{toplam_harcama:,.2f} TL")
        col2.metric(f"{bugun.strftime('%B %Y')} Ayı Toplam Ödeme", f"{bu_ayki_toplam_odeme:,.2f} TL")

        st.divider()
        st.subheader("Kategori Bazlı Masraf Dökümü")

        # KATEGORILER_TUMU (GÜNCELLENDİĞİ İÇİN 'Sigorta-Kasko' otomatik eklenecek)
        for kategori in KATEGORILER_TUMU:
            kategori_df = df_main[df_main["Masraf Türü"] == kategori]
            
            if not kategori_df.empty:
                kategori_toplam_harcama = kategori_df['Tutar'].sum()
                
                kategori_bu_ayki_odeme = 0
                if not bu_ayki_odemeler.empty: 
                    kategori_bu_ayki_odeme = bu_ayki_odemeler[
                        bu_ayki_odemeler['Kategori'] == kategori
                    ]['Ödeme Tutarı'].sum()
                
                expander_title = (
                    f"**{kategori}** | "
                    f"Toplam Harcama: **{kategori_toplam_harcama:,.2f} TL** | "
                    f"Bu Ayki Ödeme: **{kategori_bu_ayki_odeme:,.2f} TL**"
                )
                
                with st.expander(expander_title):
                    st.dataframe(
                        kategori_df[["Tarih", "KM Sayacı", "Tutar", "Açıklama", "Taksit Sayısı"]].sort_values("Tarih", ascending=False),
                        hide_index=True,
                        use_container_width=True,
                         column_config={
                            "Tarih": st.column_config.DateColumn("Tarih", format="YYYY-MM-DD"),
                            "Tutar": st.column_config.NumberColumn("Tutar", format="%.2f TL"),
                            "KM Sayacı": st.column_config.NumberColumn("KM Sayacı", format="%d km"),
                            "Taksit Sayısı": st.column_config.NumberColumn("Taksit Sayısı", format="%d"),
                        }
                    )

# --- 7. SEKME 5: VERİ YÖNETİMİ ---
with tab5:
    st.header("Veri Yönetimi ve Düzenleme")
    
    if df_main.empty:
        st.info("Görüntülenecek veya düzenlenecek bir veri yok.")
    else:
        st.subheader("Veri Filtreleme")
        col1, col2, col3 = st.columns(3)
        with col1:
            filt_turler = st.multiselect("Masraf Türüne Göre Filtrele", options=df_main['Masraf Türü'].unique())
        with col2:
            min_date = df_main['Tarih'].min().date()
            max_date = df_main['Tarih'].max().date()
            filt_tarih = st.date_input("Tarih Aralığı Seçin", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        with col3:
            filt_aciklama = st.text_input("Açıklamada Ara")

        filtrelenmis_df = df_main.copy()
        
        if filt_turler:
            filtrelenmis_df = filtrelenmis_df[filtrelenmis_df['Masraf Türü'].isin(filt_turler)]
        
        if len(filt_tarih) == 2:
            filtrelenmis_df = filtrelenmis_df[
                (filtrelenmis_df['Tarih'].dt.date >= filt_tarih[0]) &
                (filtrelenmis_df['Tarih'].dt.date <= filt_tarih[1])
            ]
            
        if filt_aciklama:
            filtrelenmis_df = filtrelenmis_df[filtrelenmis_df['Açıklama'].str.contains(filt_aciklama, case=False, na=False)]

        st.divider()

        st.subheader("Kayıtları Düzenle veya Sil")
        st.info("Bir hücreyi düzenlemek için üzerine çift tıklayın. Bir kaydı silmek için satırın başındaki kutucuğu seçip klavyenizdeki 'Delete' tuşuna basın.")
        
        editor_df = filtrelenmis_df.copy()
        
        edited_df = st.data_editor(
            editor_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "Tarih": st.column_config.DateColumn("Tarih", format="YYYY-MM-DD", step=1),
                "Tutar": st.column_config.NumberColumn("Tutar", format="%.2f TL", step=0.01),
                "Litre": st.column_config.NumberColumn("Litre", format="%.2f L", step=0.01),
                "KM Sayacı": st.column_config.NumberColumn("KM Sayacı", format="%d km"),
                "Taksit Sayısı": st.column_config.NumberColumn("Taksit Sayısı", format="%d"),
            },
            key="data_editor_key"
        )
        
        st.divider()
        
        if st.button("Tüm Değişiklikleri Kalıcı Olarak Kaydet"):
            
            # 1. Filtrelenmiş kayıtların index'lerini (yani güncellenecek/silinecek olanları) df_main'den sil.
            index_to_drop = filtrelenmis_df.index
            df_main_without_edited = df_main.drop(index=index_to_drop)
            
            # 2. Düzenlenmiş (veya silinmemiş) satırları al
            df_guncel = pd.concat([df_main_without_edited, edited_df], ignore_index=True)
            
            # Veri tiplerini tekrar doğrula
            df_guncel['Tarih'] = pd.to_datetime(df_guncel['Tarih'])
            numeric_cols = ['KM Sayacı', 'Tutar', 'Taksit Sayısı', 'Litre']
            for col in numeric_cols:
                df_guncel[col] = pd.to_numeric(df_guncel[col], errors='coerce').fillna(0)
            df_guncel['Taksit Sayısı'] = df_guncel['Taksit Sayısı'].apply(lambda x: 1 if x < 1 else int(x))
            
            df_guncel = df_guncel.replace(r'^\s*$', pd.NA, regex=True)

            save_data(df_guncel) # Bu fonksiyon artık state'i de güncelliyor
            st.success("Veritabanı (Google Sheets) başarıyla güncellendi!")
            st.rerun()