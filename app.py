import sys
import types
import io
import os
import random
import time
import base64
import requests
import json

import streamlit as st
from PIL import Image
from PyPDF2 import PdfReader
from deep_translator import GoogleTranslator
import ollama

# ─────────────────────────────────────────────────────────────────────────────
# MODULE 1 ─ CGI COMPATIBILITY SHIM (For Streamlit Stability in Python 3.13+)
# ─────────────────────────────────────────────────────────────────────────────
if "cgi" not in sys.modules:
    _cgi_stub = types.ModuleType("cgi")
    def _parse_header(line):
        parts = line.split(";")
        key = parts[0].strip()
        params = {}
        for p in parts[1:]:
            p = p.strip()
            if "=" in p:
                k, _, v = p.partition("=")
                params[k.strip()] = v.strip().strip('"')
        return key, params
    _cgi_stub.parse_header = _parse_header
    _cgi_stub.escape = lambda s, quote=False: s
    sys.modules["cgi"] = _cgi_stub

try:
    import speech_recognition as sr
    from gtts import gTTS
except ImportError:
    st.error("Please run: pip install SpeechRecognition gTTS ollama PyPDF2 deep-translator")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
INDIA_LOCATIONS = {
    "Gujarat":       ["Vadodara", "Ahmedabad", "Surat", "Rajkot"],
    "Punjab":        ["Amritsar", "Ludhiana", "Jalandhar", "Patiala"],
    "Maharashtra":   ["Mumbai", "Pune", "Nagpur", "Nashik"],
    "Uttar Pradesh": ["Kanpur", "Lucknow", "Agra", "Varanasi"],
    "Rajasthan":     ["Jaipur", "Jodhpur", "Udaipur", "Kota"],
    "Madhya Pradesh":["Bhopal", "Indore", "Gwalior", "Jabalpur"],
}

CITY_COORDS = {
    "Vadodara":  (22.3072, 73.1812),
    "Ahmedabad": (23.0225, 72.5714),
    "Surat":     (21.1702, 72.8311),
    "Rajkot":    (22.3039, 70.8022),
    "Amritsar":  (31.6340, 74.8723),
    "Ludhiana":  (30.9010, 75.8573),
    "Jalandhar": (31.3260, 75.5762),
    "Patiala":   (30.3398, 76.3869),
    "Pune":      (18.5204, 73.8567),
    "Mumbai":    (19.0760, 72.8777),
    "Nagpur":    (21.1458, 79.0882),
    "Nashik":    (19.9975, 73.7898),
    "Lucknow":   (26.8467, 80.9462),
    "Kanpur":    (26.4499, 80.3319),
    "Agra":      (27.1767, 78.0081),
    "Varanasi":  (25.3176, 82.9739),
    "Jaipur":    (26.9124, 75.7873),
    "Jodhpur":   (26.2389, 73.0243),
    "Bhopal":    (23.2599, 77.4126),
    "Indore":    (22.7196, 75.8577),
}

BASE_PRICES = {
    "Wheat":         2125,
    "Cotton":        6300,
    "Paddy (Rice)":  2040,
    "Sugarcane":      315,
    "Mustard":       5400,
    "Potato":        1200,
    "Soybean":       4500,
    "Maize":         1900,
    "Groundnut":     5800,
    "Onion":          850,
    "Tomato":        1100,
    "Garlic":        9000,
}

LANG_MAP = {
    "Hindi":   "hi",
    "Gujarati":"gu",
    "Punjabi": "pa",
    "Marathi": "mr",
    "Bengali": "bn",
    "Tamil":   "ta",
    "Telugu":  "te",
    "Kannada": "kn",
    "Odia":    "or",
    "Urdu":    "ur",
}

GOVT_SCHEMES = {
    "PM-KISAN": {
        "benefit": "₹6,000 per year in 3 installments of ₹2,000",
        "eligibility": "All small & marginal farmers with cultivable land",
        "how_to_apply": "Visit nearest Common Service Centre (CSC) or pmkisan.gov.in",
        "helpline": "155261 / 011-23381092",
    },
    "Pradhan Mantri Fasal Bima Yojana (PMFBY)": {
        "benefit": "Insurance coverage for crop loss due to natural calamities",
        "eligibility": "All farmers growing notified crops",
        "how_to_apply": "Contact nearest bank branch or insurance company before sowing",
        "helpline": "1800-180-1551",
    },
    "Kisan Credit Card (KCC)": {
        "benefit": "Short-term credit up to ₹3 lakh at 4% interest per year",
        "eligibility": "All farmers, sharecroppers, tenant farmers",
        "how_to_apply": "Apply at nearest bank with land records & Aadhaar",
        "helpline": "Contact your nearest bank branch",
    },
    "PM Kisan Samman Nidhi": {
        "benefit": "Direct income support ₹6,000/year",
        "eligibility": "Small & marginal landholder farmer families",
        "how_to_apply": "Register on pmkisan.gov.in or visit local patwari",
        "helpline": "1800-115-526",
    },
    "Soil Health Card Scheme": {
        "benefit": "Free soil testing & crop/fertilizer recommendations",
        "eligibility": "Every farmer with agricultural land",
        "how_to_apply": "Contact local Krishi Vigyan Kendra (KVK)",
        "helpline": "1800-180-1551",
    },
    "eNAM (National Agriculture Market)": {
        "benefit": "Sell crops online at best APMC mandi prices across India",
        "eligibility": "All registered farmers",
        "how_to_apply": "Register at enam.gov.in or nearest APMC",
        "helpline": "1800-270-0224",
    },
}

DISEASE_INFO = {
    "leaf blight":     {"remedy": "Spray Mancozeb (2g/L water). Remove infected leaves. Avoid overhead watering.", "prevention": "Use disease-resistant seeds. Rotate crops yearly."},
    "powdery mildew":  {"remedy": "Spray Sulfur-based fungicide or Karathane. Apply in cool mornings.", "prevention": "Ensure good air circulation. Avoid excess nitrogen."},
    "rust":            {"remedy": "Apply Propiconazole (Tilt) fungicide @ 1ml/L. Repeat after 15 days.", "prevention": "Use certified rust-resistant varieties."},
    "mosaic virus":    {"remedy": "No chemical cure. Remove & destroy infected plants immediately.", "prevention": "Control aphid insects using Imidacloprid. Use virus-free seeds."},
    "yellowing":       {"remedy": "Apply Iron Sulphate (FeSO4) 0.5% spray. Check soil pH (should be 6-7).", "prevention": "Do soil testing before sowing. Apply balanced fertilizers."},
    "wilt":            {"remedy": "Drench soil with Carbendazim 0.1% solution. Improve drainage.", "prevention": "Avoid waterlogging. Use Trichoderma-treated seeds."},
    "aphids":          {"remedy": "Spray Neem oil (5ml/L) or Imidacloprid 0.5ml/L water.", "prevention": "Introduce ladybird beetles. Yellow sticky traps."},
    "stem rot":        {"remedy": "Apply Copper oxychloride 3g/L. Remove affected stems.", "prevention": "Avoid dense planting. Use raised beds."},
    "brown spots":     {"remedy": "Spray Propiconazole + Carbendazim mix. Remove fallen leaves.", "prevention": "Balanced fertilization. Avoid excess moisture on leaves."},
    "black spots":     {"remedy": "Apply Captan or Thiram fungicide 2g/L water.", "prevention": "Avoid wetting foliage. Space plants well."},
}

CHATBOT_FAQS = {
    "fertilizer": "For most crops: Apply Urea (Nitrogen) during vegetative stage, DAP (Phosphorus) at sowing, and Potash (MOP) during fruiting. Always do soil test first. Helpline: 1800-180-1551",
    "irrigation": "Drip irrigation saves 40-50% water. For wheat: irrigate at crown root initiation, tillering, jointing & grain filling stages. Avoid overwatering — it causes root rot.",
    "pesticide":  "Always wear protective gear. Read label carefully. Mix in correct ratio. Spray in early morning or evening. Never spray before rain. Store safely away from children.",
    "sowing":     "Check local Krishi Vigyan Kendra (KVK) for season-specific advice. Generally: Kharif (June-July), Rabi (Oct-Nov), Zaid (Feb-Mar).",
    "loan":       "Kisan Credit Card (KCC) gives up to ₹3 lakh at 4% interest. Apply at nearest bank with Aadhaar + land records. PM-KISAN gives ₹6,000/year directly to bank account.",
    "mandi":      "Check eNAM app or enam.gov.in for live mandi prices. You can sell directly online and get best rates without middlemen.",
    "insurance":  "PMFBY (Pradhan Mantri Fasal Bima Yojana) covers crop loss. Premium is only 1.5-2% for Rabi crops. Apply at your bank before crop sowing.",
    "weather":    "Use IMD (India Meteorological Dept) app 'Meghdoot' for 5-day agro-weather forecast in your local language. Free on Play Store.",
    "seed":       "Always buy certified seeds from government or registered dealers. Check for ISI mark. Treat seeds with Thiram or Trichoderma before sowing.",
    "organic":    "Start with vermicompost (15-20 tonnes/acre), neem cake (200 kg/acre), and green manure. Get organic certification from APEDA. Premium pricing in market.",
}

# ─────────────────────────────────────────────────────────────────────────────
# MODULE 2 ─ PAGE CONFIG & MASTER CSS
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KrishiVaani AI",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

MASTER_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;600;800&display=swap');
:root {
    --green-deep: #1B5E20;
    --green-mid:  #2E7D32;
    --green-light:#4CAF50;
    --amber:      #F9A825;
    --white:      #FFFFFF;
    --bg-light:   #F1F8E9;
}
html, body, [data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #F1F8E9 0%, #E8F5E9 40%, #F9FBE7 100%) !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
}
[data-testid="stSidebar"] {
    background: #0d1f0e !important;
    border-right: 1px solid rgba(255,255,255,0.08);
}
[data-testid="stSidebar"] * { color: #f0fdf4 !important; }
[data-testid="stSidebar"] .stButton > button {
    background: rgba(46,125,50,0.25) !important;
    border: 1px solid rgba(76,175,80,0.3) !important;
    text-align: left !important;
    justify-content: flex-start !important;
    margin-bottom: 4px;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(46,125,50,0.5) !important;
    transform: translateX(4px) !important;
    box-shadow: none !important;
}
.hero-banner {
    background: linear-gradient(120deg, var(--green-deep) 0%, var(--green-mid) 60%, #388E3C 100%);
    border-radius: 20px;
    padding: 2.2rem 2.5rem;
    margin-bottom: 1.8rem;
    color: white;
    box-shadow: 0 8px 32px rgba(27,94,32,0.25);
    position: relative;
    overflow: hidden;
}
.hero-banner::after {
    content: '';
    position: absolute;
    right: -30px; top: -30px;
    width: 200px; height: 200px;
    background: rgba(255,255,255,0.04);
    border-radius: 50%;
}
.hero-banner h1 { font-size: 2rem; margin: 0 0 6px; font-weight: 800; }
.hero-banner p  { margin: 0; opacity: 0.85; font-size: 0.95rem; }
.kv-card {
    background: white;
    border-radius: 18px;
    padding: 1.8rem;
    box-shadow: 0 4px 20px rgba(0,0,0,0.05);
    border: 1px solid rgba(0,0,0,0.05);
    margin-bottom: 1.5rem;
}
.stButton > button {
    background: var(--green-mid) !important;
    color: white !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    border: none !important;
    padding: 0.6rem 2rem !important;
    width: 100%;
    transition: all 0.25s ease;
}
.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(46,125,50,0.35) !important;
    background: #1B5E20 !important;
}
.metric-box {
    background: linear-gradient(135deg, #E8F5E9, #F1F8E9);
    border: 1px solid #C8E6C9;
    border-radius: 14px;
    padding: 1.2rem;
    text-align: center;
    margin-bottom: 10px;
}
.metric-box h4 { margin: 0 0 4px; color: #388E3C; font-size: 0.9rem; }
.metric-box h2 { margin: 0; font-size: 1.8rem; color: #1B5E20; font-weight: 800; }
.ner-box {
    background: rgba(249,168,37,0.08);
    border-left: 4px solid #F9A825;
    padding: 14px 18px;
    border-radius: 0 12px 12px 0;
    margin-bottom: 18px;
}
.ner-box h4 { color: #F57F17; margin: 0 0 6px; font-size: 0.95rem; }
.ner-box p  { margin: 0; font-size: 0.9rem; color: #333; line-height: 1.6; }
.advice-box {
    background: linear-gradient(135deg, #E8F5E9 0%, #F9FBE7 100%);
    border: 1px solid #A5D6A7;
    border-radius: 14px;
    padding: 1.4rem;
    margin-top: 1rem;
}
.advice-box h4 { color: #2E7D32; margin: 0 0 8px; }
.disease-alert {
    background: #FFF3E0;
    border: 1px solid #FFB74D;
    border-radius: 14px;
    padding: 1.2rem;
    margin-top: 1rem;
}
.disease-alert h4 { color: #E65100; margin: 0 0 6px; }
.scheme-card {
    background: linear-gradient(135deg, #E3F2FD 0%, #F1F8E9 100%);
    border: 1px solid #90CAF9;
    border-radius: 14px;
    padding: 1.3rem;
    margin-bottom: 1rem;
}
.scheme-card h3 { color: #1565C0; margin: 0 0 8px; font-size: 1.05rem; }
.scheme-card .benefit { color: #2E7D32; font-weight: 600; font-size: 0.95rem; }
.scheme-card .detail  { color: #555; font-size: 0.88rem; margin-top: 6px; line-height: 1.6; }
.helpline-badge {
    display: inline-block;
    background: #1565C0;
    color: white !important;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-top: 8px;
}
.chat-bubble-bot {
    background: #E8F5E9;
    border: 1px solid #C8E6C9;
    border-radius: 0 16px 16px 16px;
    padding: 12px 16px;
    margin: 8px 0 8px 0;
    max-width: 85%;
    font-size: 0.92rem;
    color: #1A2E1A;
    line-height: 1.6;
}
.chat-bubble-user {
    background: #1B5E20;
    color: white;
    border-radius: 16px 0 16px 16px;
    padding: 12px 16px;
    margin: 8px 0 8px auto;
    max-width: 80%;
    font-size: 0.92rem;
    text-align: right;
}
.price-card {
    background: linear-gradient(to right, #f8fafc, #e2e8f0);
    padding: 25px;
    border-radius: 18px;
    text-align: center;
    margin-top: 20px;
    border: 1px solid #cbd5e1;
}
.sidebar-logo { text-align: center; padding: 1rem 0 0.5rem; }
.sidebar-logo h2 { font-size: 1.4rem; font-weight: 800; margin: 4px 0 0; }
.sidebar-logo p  { font-size: 0.75rem; opacity: 0.55; margin: 0; }
</style>
"""
st.markdown(MASTER_CSS, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# FULL UI TRANSLATION DICTIONARY
# Keys: EN | HI | GU | PA
# ─────────────────────────────────────────────────────────────────────────────
UI_TEXT = {
    # Sidebar
    "subtitle":          {"EN": "Local AI · Offline · Multilingual",    "HI": "लोकल AI · ऑफलाइन · बहुभाषी",            "GU": "લોકલ AI · ઑફલાઇન · બહુભાષી",         "PA": "ਲੋਕਲ AI · ਆਫਲਾਈਨ · ਬਹੁਭਾਸ਼ੀ"},
    "navigate":          {"EN": "📱 Navigate",                            "HI": "📱 मेनू",                               "GU": "📱 મેનૂ",                               "PA": "📱 ਮੀਨੂ"},
    "llama_active":      {"EN": "● Llama 3 Active (Local)",             "HI": "● Llama 3 चालू है (Local)",             "GU": "● Llama 3 ચાલુ છે (Local)",           "PA": "● Llama 3 ਚਾਲੂ ਹੈ (Local)"},
    "helpline_info":     {"EN": "📞 Kisan Helpline: **1800-180-1551**", "HI": "📞 किसान हेल्पलाइन: **1800-180-1551**","GU": "📞 ખેડૂત હેલ્પલાઇન: **1800-180-1551**","PA": "📞 ਕਿਸਾਨ ਹੈਲਪਲਾਈਨ: **1800-180-1551**"},
    # Page nav labels
    "nav_advisor":       {"EN": "🎙️ Smart Advisor",      "HI": "🎙️ स्मार्ट सलाहकार",   "GU": "🎙️ સ્માર્ટ સલાહ",        "PA": "🎙️ ਸਮਾਰਟ ਸਲਾਹਕਾਰ"},
    "nav_disease":       {"EN": "🍃 Disease Detector",   "HI": "🍃 रोग पहचानकर्ता",     "GU": "🍃 રોગ શોધક",              "PA": "🍃 ਰੋਗ ਖੋਜਕ"},
    "nav_translator":    {"EN": "🌍 Translator",          "HI": "🌍 अनुवादक",             "GU": "🌍 અનુવાદક",               "PA": "🌍 ਅਨੁਵਾਦਕ"},
    "nav_weather":       {"EN": "☁️ Weather Alerts",      "HI": "☁️ मौसम चेतावनी",       "GU": "☁️ હવામાન સૂચના",         "PA": "☁️ ਮੌਸਮ ਚੇਤਾਵਨੀ"},
    "nav_mandi":         {"EN": "📈 Mandi Prices",        "HI": "📈 मंडी भाव",            "GU": "📈 માર્કેટ ભાવ",            "PA": "📈 ਮੰਡੀ ਭਾਅ"},
    "nav_schemes":       {"EN": "🏛️ Govt Schemes",       "HI": "🏛️ सरकारी योजनाएं",     "GU": "🏛️ સરકારી યોજનાઓ",       "PA": "🏛️ ਸਰਕਾਰੀ ਯੋਜਨਾਵਾਂ"},
    "nav_chatbot":       {"EN": "💬 Chatbot Helpline",    "HI": "💬 चैटबॉट सहायता",      "GU": "💬 ચેટબૉટ મદદ",            "PA": "💬 ਚੈਟਬੋਟ ਮਦਦ"},
    "nav_doc":           {"EN": "📜 Doc Summarizer",      "HI": "📜 दस्तावेज़ सारांश",    "GU": "📜 દસ્તાવેજ સારાંશ",       "PA": "📜 ਦਸਤਾਵੇਜ਼ ਸਾਰ"},
    # Smart Advisor page
    "advisor_title":     {"EN": "🎙️ KrishiVaani AI 🌾 Smart Agri-Advisor",          "HI": "🎙️KrishiVaani AI🌾 स्मार्ट कृषि-सलाहकार",      "GU": "🎙️KrishiVaani AI🌾 સ્માર્ટ કૃષિ-સલાહ",          "PA": "🎙️ ਸਮਾਰਟ ਖੇਤੀ-ਸਲਾਹਕਾਰ"},
    "advisor_sub":       {"EN": "Ask by voice or text — AI answers in your language",
                          "HI": "बोलो या लिखो — AI आपकी भाषा में जवाब देगा",
                          "GU": "બોલો અથવા લખો — AI તમારી ભાષામાં જવાબ આપશે",
                          "PA": "ਬੋਲੋ ਜਾਂ ਲਿਖੋ — AI ਤੁਹਾਡੀ ਭਾਸ਼ਾ ਵਿੱਚ ਜਵਾਬ ਦੇਵੇਗਾ"},
    "record_label":      {"EN": "🎤 Record your farming question",  "HI": "🎤 अपना सवाल रिकॉर्ड करें", "GU": "🎤 તમારો સવાલ રેકોર્ડ કરો",  "PA": "🎤 ਆਪਣਾ ਸਵਾਲ ਰਿਕਾਰਡ ਕਰੋ"},
    "type_label":        {"EN": "✏️ Or type your question here",   "HI": "✏️ या यहाँ टाइप करें",       "GU": "✏️ અથવા અહીં ટાઇપ કરો",      "PA": "✏️ ਜਾਂ ਇੱਥੇ ਟਾਈਪ ਕਰੋ"},
    "analyze_btn":       {"EN": "🔍 Analyze with NER + AI",        "HI": "🔍 NER + AI से विश्लेषण करो", "GU": "🔍 NER + AI થી વિશ્લેષણ કરો","PA": "🔍 NER + AI ਨਾਲ ਵਿਸ਼ਲੇਸ਼ਣ ਕਰੋ"},
    "clear_btn":         {"EN": "🗑️ Clear",                        "HI": "🗑️ साफ करें",                "GU": "🗑️ સાફ કરો",                 "PA": "🗑️ ਸਾਫ਼ ਕਰੋ"},
    "ner_heading":       {"EN": "🔍 NER Entity Extraction",        "HI": "🔍 NER इकाई निष्कर्षण",     "GU": "🔍 NER એન્ટિટી કાઢવી",        "PA": "🔍 NER ਇਕਾਈ ਕੱਢਣਾ"},
    "advice_heading":    {"EN": "💡 KrishiVaani Advice",           "HI": "💡 कृषिवाणी की सलाह",       "GU": "💡 કૃષિવાણી સલાહ",            "PA": "💡 ਕ੍ਰਿਸ਼ੀਵਾਣੀ ਸਲਾਹ"},
    "try_examples":      {"EN": "💡 Try these example questions:",  "HI": "💡 ये सवाल आज़माएं:",        "GU": "💡 આ ઉદાહરણ પ્રશ્નો અજમાવો:", "PA": "💡 ਇਹ ਉਦਾਹਰਣ ਸਵਾਲ ਅਜ਼ਮਾਓ:"},
    # Disease page
    "disease_title":     {"EN": "🍃 Crop Disease Detector",        "HI": "🍃 फसल रोग पहचानकर्ता",     "GU": "🍃 પાક રોગ શોધક",              "PA": "🍃 ਫਸਲ ਰੋਗ ਖੋਜਕ"},
    "disease_sub":       {"EN": "Upload leaf photo OR describe symptoms — AI diagnoses & prescribes",
                          "HI": "पत्ती की फोटो अपलोड करें या लक्षण बताएं — AI इलाज बताएगा",
                          "GU": "પાનની ફોટો અપલોડ કરો અથવા લક્ષણ જણાવો — AI સારવાર આપશે",
                          "PA": "ਪੱਤੇ ਦੀ ਫੋਟੋ ਅੱਪਲੋਡ ਕਰੋ ਜਾਂ ਲੱਛਣ ਦੱਸੋ — AI ਇਲਾਜ ਦੱਸੇਗਾ"},
    "diagnose_btn":      {"EN": "🔬 Diagnose Disease",             "HI": "🔬 रोग पहचानें",             "GU": "🔬 રોગ ઓળખો",                 "PA": "🔬 ਰੋਗ ਪਛਾਣੋ"},
    "get_diagnosis_btn": {"EN": "🌿 Get Diagnosis",                "HI": "🌿 इलाज जानें",              "GU": "🌿 ઉપચાર જાણો",               "PA": "🌿 ਇਲਾਜ ਜਾਣੋ"},
    # Translator page
    "trans_title":       {"EN": "🌍 Multilingual Translator",      "HI": "🌍 बहुभाषी अनुवादक",         "GU": "🌍 બહુભાષી અનુવાદક",          "PA": "🌍 ਬਹੁਭਾਸ਼ੀ અਨੁਵਾਦਕ"},
    "trans_sub":         {"EN": "10+ Indian languages • Voice output",
                          "HI": "10+ भारतीय भाषाएं • आवाज़ आउटपुट",
                          "GU": "10+ ભારતીય ભાષાઓ • અવાજ આઉટપુટ",
                          "PA": "10+ ਭਾਰਤੀ ਭਾਸ਼ਾਵਾਂ • ਆਵਾਜ਼ ਆਉટપੁੱਟ"},
    "translate_btn":     {"EN": "🌐 Translate Now",                "HI": "🌐 अभी अनुवाद करें",         "GU": "🌐 હવે અનુવાદ કરો",            "PA": "🌐 ਹੁਣ અનુવાદ કરો"},
    # Weather page
    "weather_title":     {"EN": "☁️ Smart Weather Alerts",         "HI": "☁️ मौसम चेतावनी",            "GU": "☁️ હવામાન ચેતવણી",            "PA": "☁️ ਮੌਸਮ ਚੇਤਾਵਨੀ"},
    "weather_sub":       {"EN": "Real-time weather + AI farming advisory for your district",
                          "HI": "आपके जिले के लिए असली मौसम + AI खेती सलाह",
                          "GU": "તમારા જિલ્લા માટે લાઇવ હવામાન + AI ખેતી સલાહ",
                          "PA": "ਤੁਹਾਡੇ ਜ਼ਿਲ੍ਹੇ ਲਈ ਲਾਈਵ ਮੌਸਮ + AI ਖੇਤੀ ਸਲਾਹ"},
    "fetch_weather_btn": {"EN": "🌤️ Get Weather + AI Advisory",   "HI": "🌤️ मौसम + AI सलाह लें",    "GU": "🌤️ હવામાન + AI સલાહ મેળવો",  "PA": "🌤️ ਮੌਸਮ + AI ਸਲਾਹ ਲਓ"},
    "ai_advisory":       {"EN": "🤖 AI Farming Advisory",          "HI": "🤖 AI खेती सलाह",            "GU": "🤖 AI ખેતી સલાહ",              "PA": "🤖 AI ਖੇਤੀ ਸਲਾਹ"},
    "select_state":      {"EN": "📍 Select State",                 "HI": "📍 राज्य चुनें",             "GU": "📍 રાજ્ય પસંદ કરો",           "PA": "📍 ਰਾਜ ਚੁਣੋ"},
    "select_district":   {"EN": "🏘️ Select District",             "HI": "🏘️ जिला चुनें",             "GU": "🏘️ જિલ્લો પસંદ કરો",         "PA": "🏘️ ਜ਼ਿਲ੍ਹਾ ਚੁਣੋ"},
    "forecast_5day":     {"EN": "📅 5-Day Forecast",               "HI": "📅 5-दिन का पूर्वानुमान",    "GU": "📅 5-દિવસની આગાહી",            "PA": "📅 5-ਦਿਨ ਦਾ ਅਨੁਮਾਨ"},
    # Mandi page
    "mandi_title":       {"EN": "📈 Mandi Price Tracker",          "HI": "📈 मंडी भाव ट्रैकर",         "GU": "📈 માર્કેટ ભાવ ટ્રૅકર",       "PA": "📈 ਮੰਡੀ ਭਾਅ ਟਰੈਕਰ"},
    "mandi_sub":         {"EN": "Live APMC prices + AI price prediction for smart selling",
                          "HI": "लाइव APMC भाव + AI प्राइस प्रिडिक्शन",
                          "GU": "લાઇવ APMC ભાવ + AI ભાવ પ્રિડિક્શન",
                          "PA": "ਲਾਈਵ APMC ਭਾਅ + AI ਭਾਅ ਭਵਿੱਖਬਾਣੀ"},
    "check_rates_btn":   {"EN": "💹 Check Mandi Rates",            "HI": "💹 मंडी भाव देखें",          "GU": "💹 ભાવ ચેક કરો",              "PA": "💹 ਭਾਅ ਚੈੱਕ ਕਰੋ"},
    "selling_advice":    {"EN": "💡 Selling Advice",               "HI": "💡 बेचने की सलाह",           "GU": "💡 વેચાણ સલાહ",               "PA": "💡 ਵੇਚਣ ਦੀ ਸਲਾਹ"},
    "predict_btn":       {"EN": "🔮 View Price Trends",            "HI": "🔮 भाव ट्रेंड देखें",        "GU": "🔮 ભાવ ટ્રેન્ડ જુઓ",          "PA": "🔮 ਭਾਅ ਰੁਝਾਨ ਦੇਖੋ"},
    # Schemes page
    "schemes_title":     {"EN": "🏛️ Government Scheme Advisor",   "HI": "🏛️ सरकारी योजना सलाहकार",  "GU": "🏛️ સરકારી યોજના સલાહ",       "PA": "🏛️ ਸਰਕਾਰੀ ਯੋਜਨਾ ਸਲਾਹਕਾਰ"},
    "schemes_sub":       {"EN": "Know your rights • PM-KISAN • PMFBY • KCC • eNAM",
                          "HI": "अपने अधिकार जानें • PM-KISAN • PMFBY • KCC • eNAM",
                          "GU": "તમારા હક્ક જાણો • PM-KISAN • PMFBY • KCC • eNAM",
                          "PA": "ਆਪਣੇ ਅਧਿਕਾਰ ਜਾਣੋ • PM-KISAN • PMFBY • KCC • eNAM"},
    "check_eligibility": {"EN": "🔍 Check Eligibility",            "HI": "🔍 पात्रता जांचें",         "GU": "🔍 પાત્રતા તપાસો",             "PA": "🔍 ਯੋਗਤਾ ਜਾਂਚੋ"},
    "find_schemes_btn":  {"EN": "🎯 Find My Eligible Schemes",     "HI": "🎯 मेरी पात्र योजनाएं ढूंढें","GU": "🎯 મારી લાયક યોજનાઓ શોધો",    "PA": "🔎 ਯੋਗ ਯੋਜਨਾਵਾਂ ਲੱਭੋ"},
    "eligible_schemes":  {"EN": "✅ Your Eligible Schemes",        "HI": "✅ आपकी पात्र योजनाएं",      "GU": "✅ તમારી લાયક યોજનાઓ",         "PA": "✅ ਤੁਹਾਡੀਆਂ ਯੋਗ ਯੋਜਨਾਵਾਂ"},
    "quick_ref":         {"EN": "📋 All Major Schemes — Quick Ref","HI": "📋 सभी मुख्य योजनाएं — त्वरित संदर्भ", "GU": "📋 તમામ મુખ્ય યોજનાઓ — ઝડપી સંદર્ભ", "PA": "📋 ਸਾਰੀਆਂ ਮੁੱਖ ਯੋਜਨਾਵਾਂ — ਤੁਰੰਤ ਹਵਾਲਾ"},
    # Chatbot page
    "chatbot_title":     {"EN": "💬 KrishiVaani Chatbot",          "HI": "💬 कृषिवाणी चैटबॉट",         "GU": "💬 કૃષિવાણી ચેટબૉટ",          "PA": "💬 ਕ੍ਰਿਸ਼ੀਵਾਣੀ ਚੈਟਬੋਟ"},
    "chatbot_sub":       {"EN": "24/7 farming helpline • Ask anything about crops, loans, weather",
                          "HI": "24/7 किसान सहायता • फसल, कर्ज, मौसम — कुछ भी पूछो",
                          "GU": "24/7 ખેડૂત સહાય • પાક, લોન, હવામાન — ગમે તે પૂછો",
                          "PA": "24/7 ਕਿਸਾਨ ਸਹਾਇਤਾ • ਫਸਲ, ਕਰਜ਼, ਮੌਸਮ — ਕੁਝ ਵੀ ਪੁੱਛੋ"},
    "send_btn":          {"EN": "📤 Send Message",                 "HI": "📤 संदेश भेजें",             "GU": "📤 સંદેશ મોકલો",              "PA": "📤 ਸੁਨੇਹਾ ਭੇਜੋ"},
    "clear_chat_btn":    {"EN": "🗑️ Clear Chat",                   "HI": "🗑️ चैट साफ करें",            "GU": "🗑️ ચેટ સાફ કરો",              "PA": "🗑️ ਚੈਟ ਸਾਫ਼ ਕਰੋ"},
    "quick_questions":   {"EN": "⚡ Quick Questions",               "HI": "⚡ त्वरित सवाल",             "GU": "⚡ ઝડપી સવાલ",                "PA": "⚡ ਤੇਜ਼ ਸਵਾਲ"},
    "emergency_help":    {"EN": "📞 Emergency Helpline:",          "HI": "📞 आपातकालीन हेल्पलाइन:",    "GU": "📞 ઇમર્જન્સી હેલ્પલાઇન:",      "PA": "📞 ਐਮਰਜੈਂਸੀ ਹੈਲਪਲਾਈਨ:"},
    # Doc summarizer page
    "doc_title":         {"EN": "📜 Document Summarizer",          "HI": "📜 दस्तावेज़ सारांश",         "GU": "📜 દસ્તાવેજ સારાંશ",          "PA": "📜 ਦਸਤਾਵੇਜ਼ ਸਾਰ"},
    "doc_sub":           {"EN": "Upload govt PDFs — AI explains in simple language",
                          "HI": "सरकारी PDF अपलोड करें — AI सरल भाषा में समझाएगा",
                          "GU": "સરકારી PDF અપલોડ કરો — AI સરળ ભાષામાં સમજાવશે",
                          "PA": "ਸਰકારી PDF ਅੱਪਲੋਡ ਕਰੋ — AI ਸਰਲ ਭਾਸ਼ਾ ਵਿੱਚ ਸਮਝਾਏਗਾ"},
    "summary_btn":       {"EN": "📋 Generate Summary (5 Points)",  "HI": "📋 सारांश बनाएं (5 बिंदु)", "GU": "📋 સારાંશ બનાવો (5 મુદ્દા)", "PA": "📋 ਸਾਰ ਬਣਾਓ (5 ਨੁਕਤੇ)"},
    "extract_btn":       {"EN": "❓ Extract Key Numbers & Dates",   "HI": "❓ मुख्य संख्याएं और तारीखें निकालें", "GU": "❓ મુખ્ય સંખ્યા અને તારીખો કાઢો",   "PA": "❓ ਮੁੱਖ ਨੰਬਰ ਅਤੇ ਤਾਰੀਖਾਂ ਕੱਢੋ"},
    "translate_summary_btn": {"EN": "🌐 Translate Summary to Regional", "HI": "🌐 सारांश क्षेत्रीय भाषा में अनुवाद करें", "GU": "🌐 સારાંશ પ્રાદેશિક ભાષામાં અનુવાદ કરો", "PA": "🌐 ਸਾਰ ਖੇਤਰੀ ਭਾਸ਼ਾ ਵਿੱਚ ਅਨੁਵਾਦ ਕਰੋ"},
    # Common
    "transcribing":      {"EN": "Transcribing your voice...",       "HI": "आवाज़ पहचान हो रही है...",   "GU": "અવાજ ઓળખ ચાલી રહી છે...",   "PA": "ਆਵਾਜ਼ ਪਛਾਣ ਹੋ ਰਹੀ ਹੈ..."},
    "analyzing":         {"EN": "NLP Engine working...",            "HI": "NLP इंजन काम कर रहा है...", "GU": "NLP એન્જિન કામ કરી રહ્યું છે...","PA": "NLP ਇੰਜਣ ਕੰਮ ਕਰ ਰਿਹਾ ਹੈ..."},
    "enter_question":    {"EN": "Please record or type a question first.",
                          "HI": "कृपया पहले सवाल रिकॉर्ड करें या टाइप करें।",
                          "GU": "કૃપા કરી પહેલા સવાલ રેકોર્ડ કરો અથવા ટાઇપ કરો.",
                          "PA": "ਕਿਰਪਾ ਕਰਕੇ ਪਹਿਲਾਂ ਸਵਾਲ ਰਿਕਾਰਡ ਕਰੋ ਜਾਂ ਟਾਈਪ ਕਰੋ।"},
}

# Language → TTS code and Ollama language word
LANG_META = {
    "EN": {"code": "en",  "word": "English",  "sr": "en-IN"},
    "HI": {"code": "hi",  "word": "Hindi",    "sr": "hi-IN"},
    "GU": {"code": "gu",  "word": "Gujarati", "sr": "gu-IN"},
    "PA": {"code": "pa",  "word": "Punjabi",  "sr": "pa-IN"},
}

def T(key):
    """Return UI text for current language."""
    return UI_TEXT.get(key, {}).get(st.session_state.lang, UI_TEXT.get(key, {}).get("EN", key))

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────────────────
if "page"          not in st.session_state: st.session_state.page = "query"
if "lang"          not in st.session_state: st.session_state.lang = "EN"
if "query_text"    not in st.session_state: st.session_state.query_text = ""
if "chat_history"  not in st.session_state: st.session_state.chat_history = []
if "target_lang"   not in st.session_state: st.session_state.target_lang = "Hindi"

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div class='sidebar-logo'>
        <div style='font-size:2.5rem;'>🌾</div>
        <h2>KrishiVaani</h2>
        <p>{T('subtitle')}</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    # ── 4-language selector ──────────────────────────────────────────────────
    st.markdown("<p style='font-size:0.8rem;opacity:0.7;margin-bottom:4px;'>🌐 Language / भाषा / ભાષા / ਭਾਸ਼ਾ</p>", unsafe_allow_html=True)
    lang_options = {
        "🇬🇧 English": "EN",
        "🇮🇳 हिन्दी":   "HI",
        "🌿 ગુજરાતી": "GU",
        "🌾 ਪੰਜਾਬੀ":   "PA",
    }
    chosen_label = st.radio(
        "lang_radio", list(lang_options.keys()),
        index=list(lang_options.values()).index(st.session_state.lang),
        label_visibility="collapsed",
    )
    # If language changed, reset chat history so responses regenerate in new lang
    new_lang = lang_options[chosen_label]
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.session_state.chat_history = []
        st.rerun()

    st.markdown("---")
    st.markdown(f"**{T('navigate')}**")
    pages = [
        (T("nav_advisor"),    "query"),
        (T("nav_disease"),    "disease"),
        (T("nav_translator"), "translator"),
        (T("nav_weather"),    "weather"),
        (T("nav_mandi"),      "mandi"),
        (T("nav_schemes"),    "schemes"),
        (T("nav_chatbot"),    "chatbot"),
        (T("nav_doc"),        "doc_lab"),
    ]
    for label, key in pages:
        if st.button(label, key=f"btn_{key}"):
            st.session_state.page = key

    st.markdown("---")
    st.success(T("llama_active"))
    st.info(T("helpline_info"))

# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
def speak(text, lang_code="en"):
    try:
        tts = gTTS(text=text, lang=lang_code, slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        st.audio(fp, format="audio/mp3", autoplay=True)
    except Exception as e:
        st.warning(f"TTS unavailable: {e}")

def ollama_chat(prompt, model="llama3"):
    try:
        response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        return response["message"]["content"]
    except Exception as e:
        return f"⚠️ Ollama error: {e}. Make sure Ollama is running with 'ollama serve' and llama3 is pulled."

# Derived lang helpers (always reflect current session lang)
def lang_code(): return LANG_META[st.session_state.lang]["code"]
def lang_word(): return LANG_META[st.session_state.lang]["word"]
def lang_sr():   return LANG_META[st.session_state.lang]["sr"]

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: SMART ADVISOR (Voice + NER + AI)
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "query":
    st.markdown(f'<div class="hero-banner"><h1>{T("advisor_title")}</h1><p>{T("advisor_sub")}</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="kv-card">', unsafe_allow_html=True)
    st.markdown(f"#### {T('record_label')}")
    audio_bytes = st.audio_input(T("record_label"))
    if audio_bytes:
        with st.spinner(T("transcribing")):
            r = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(audio_bytes.getvalue())) as source:
                audio_data = r.record(source)
                try:
                    recognized = r.recognize_google(audio_data, language=lang_sr())
                    st.session_state.query_text = recognized
                    st.success(f"✅ Recognized: {recognized}")
                except sr.UnknownValueError:
                    st.error("Could not understand audio. Please speak clearly and try again.")
                except sr.RequestError as e:
                    st.error(f"Speech service error: {e}")

    user_query = st.text_input(T("type_label"), value=st.session_state.query_text,
                                placeholder="e.g. Meri gehun ki fasal mein pili pattiyan aa rahi hain...")

    col1, col2 = st.columns([2, 1])
    with col1:
        analyze = st.button(T("analyze_btn"), key="analyze_btn")
    with col2:
        clear = st.button(T("clear_btn"), key="clear_btn")

    if clear:
        st.session_state.query_text = ""
        st.rerun()

    if analyze and user_query:
        with st.spinner(T("analyzing")):

            # ── Step 1: NER ──────────────────────────────────────────────
            ner_prompt = f"""Extract agricultural entities from: "{user_query}"
Identify: FARMER_NAME, CROP, LOCATION, DISEASE_SYMPTOM, FERTILIZER, PEST.
Format strictly as:
FARMER_NAME: [name or None]
CROP: [crop name or None]  
LOCATION: [place or None]
DISEASE_SYMPTOM: [symptom or None]
FERTILIZER: [fertilizer or None]
PEST: [pest or None]
Only output the formatted list, nothing else."""
            entities = ollama_chat(ner_prompt)

            st.markdown(f"""<div class='ner-box'>
<h4>{T('ner_heading')}</h4>
<p>{entities.replace(chr(10), '<br>')}</p>
</div>""", unsafe_allow_html=True)

            # ── Step 2: Main advice ──────────────────────────────────────
            advice_prompt = f"""You are KrishiVaani — a friendly, expert agricultural assistant for Indian farmers.
Answer the following farmer's question in simple, easy-to-understand {lang_word()}.
Provide practical, actionable advice in 4-5 sentences. Include:
- What the problem likely is
- Immediate action to take  
- Product/chemical name if needed (with dosage)
- One prevention tip

Farmer's question: {user_query}"""
            advice = ollama_chat(advice_prompt)

            st.markdown(f"""<div class='advice-box'>
<h4>{T('advice_heading')}</h4>
<p>{advice}</p>
</div>""", unsafe_allow_html=True)

            # ── Step 3: TTS ──────────────────────────────────────────────
            speak(advice, lang_code())

    elif analyze and not user_query:
        st.warning(T("enter_question"))

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Quick example queries ─────────────────────────────────────────────
    st.markdown(f"#### {T('try_examples')}")
    examples = {
        "EN": ["Wheat leaves have yellow patches, what to do?",
               "Which fertilizer for cotton crop?",
               "Tomato plant leaves have brown spots?",
               "Which crop should I sow in Kharif season?"],
        "HI": ["मेरी गेहूं की फसल में पीली पत्तियां आ रही हैं",
               "कपास में कौन सा खाद डालना चाहिए?",
               "टमाटर के पत्तों पर भूरे दाग हैं, क्या करें?",
               "खरीफ सीजन में कौन सी फसल लगाऊं?"],
        "GU": ["ઘઉંના પાંદડા પીળા થઈ રહ્યા છે, શું કરવું?",
               "કપાસ માટે કયું ખાતર આપવું?",
               "ટામેટાના પાંદડા પર ભૂરા ડાઘ છે?",
               "ખરીફ સીઝનમાં કઈ ફસલ વાવવી?"],
        "PA": ["ਕਣਕ ਦੇ ਪੱਤੇ ਪੀਲੇ ਹੋ ਰਹੇ ਹਨ, ਕੀ ਕਰੀਏ?",
               "ਕਪਾਹ ਲਈ ਕਿਹੜੀ ਖਾਦ ਪਾਉਣੀ?",
               "ਟਮਾਟਰ ਦੇ ਪੱਤਿਆਂ ਤੇ ਭੂਰੇ ਧੱਬੇ ਹਨ?",
               "ਖਰੀਫ਼ ਸੀਜ਼ਨ ਵਿੱਚ ਕਿਹੜੀ ਫਸਲ ਬੀਜਾਂ?"],
    }
    ex_list = examples.get(st.session_state.lang, examples["EN"])
    cols = st.columns(2)
    for i, ex in enumerate(ex_list):
        with cols[i % 2]:
            if st.button(f"💬 {ex}", key=f"ex_{i}"):
                st.session_state.query_text = ex
                st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: LEAF DISEASE DETECTOR
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "disease":
    st.markdown(f'<div class="hero-banner"><h1>{T("disease_title")}</h1><p>{T("disease_sub")}</p></div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📸 Upload Leaf Image", "✍️ Describe Symptoms"])

    # ── Tab 1: Image Upload ───────────────────────────────────────────────
    with tab1:
        st.markdown('<div class="kv-card">', unsafe_allow_html=True)
        st.markdown("#### 📷 Upload a photo of your diseased crop leaf")
        uploaded_image = st.file_uploader("Choose leaf image (JPG / PNG)", type=["jpg", "jpeg", "png"])

        crop_type = st.selectbox("🌱 Which crop is this?",
                                  ["Wheat", "Rice", "Cotton", "Tomato", "Potato", "Maize",
                                   "Sugarcane", "Soybean", "Mustard", "Groundnut", "Other"])

        if uploaded_image:
            img = Image.open(uploaded_image)
            col1, col2 = st.columns([1, 2])
            with col1:
                st.image(img, caption="Uploaded leaf", use_container_width=True)
            with col2:
                st.info("🤖 AI will analyze visual symptoms and cross-reference with agricultural disease database.")
                if st.button(T("diagnose_btn")):
                    with st.spinner("Analyzing leaf image with AI vision..."):
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG")
                        img_b64 = base64.b64encode(buf.getvalue()).decode()

                        diagnosis_prompt = f"""You are an expert plant pathologist and agricultural scientist.
A farmer has uploaded an image of a {crop_type} leaf that appears diseased.
Based on common {crop_type} diseases in India, provide:
1. DISEASE NAME: Most likely disease
2. CONFIDENCE: High/Medium/Low
3. SYMPTOMS TO LOOK FOR: 3 visual signs
4. IMMEDIATE TREATMENT: Specific fungicide/pesticide with dosage
5. ORGANIC ALTERNATIVE: Natural remedy
6. PREVENTION: How to avoid next season
7. WHEN TO SPRAY: Best time of day
Respond in simple {lang_word()} that a farmer can understand."""

                        diagnosis = ollama_chat(diagnosis_prompt)

                        st.markdown(f"""<div class='disease-alert'>
<h4>🔬 AI Diagnosis Report — {crop_type}</h4>
<p style='font-size:0.92rem; line-height:1.7;'>{diagnosis.replace(chr(10),'<br>')}</p>
</div>""", unsafe_allow_html=True)
                        speak(diagnosis, lang_code())

        st.markdown('</div>', unsafe_allow_html=True)

    # ── Tab 2: Symptom Description ────────────────────────────────────────
    with tab2:
        st.markdown('<div class="kv-card">', unsafe_allow_html=True)
        st.markdown("#### ✍️ Describe what you see on your crop")

        col1, col2 = st.columns(2)
        with col1:
            crop_s = st.selectbox("Crop name", ["Wheat", "Rice", "Cotton", "Tomato", "Potato", "Maize",
                                                  "Sugarcane", "Mustard", "Groundnut", "Other"], key="crop_sym")
            symptom_part = st.selectbox("Affected part", ["Leaves", "Stem", "Roots", "Fruit", "Whole Plant"])
        with col2:
            symptom_color = st.selectbox("What color?", ["Yellow", "Brown", "Black", "White powder", "Orange/Rust", "Dark green", "Pale/Bleached"])
            symptom_pattern = st.selectbox("Pattern seen", ["Spots/Patches", "Stripes", "Wilting", "Curling", "Holes", "Rotting", "Powdery coating"])

        extra_desc = st.text_area("Any other details? (optional)",
                                   placeholder="e.g. started from lower leaves, spreading fast, after heavy rain...")

        if st.button(T("get_diagnosis_btn")):
            with st.spinner("Diagnosing..."):
                sym_prompt = f"""You are a plant disease expert. A farmer describes these symptoms:
Crop: {crop_s}
Affected part: {symptom_part}
Color observed: {symptom_color}
Pattern: {symptom_pattern}
Additional details: {extra_desc if extra_desc else 'None'}

Diagnose the disease and provide:
1. LIKELY DISEASE: Name it clearly
2. CAUSE: Fungal/Bacterial/Viral/Pest
3. TREATMENT: Chemical name + dosage (e.g. Mancozeb 2g per litre of water)
4. ORGANIC OPTION: Neem oil, etc.
5. WHEN TO ACT: Urgency level (Immediate/Within 3 days/Monitor)
6. SPRAY TIMING: Morning or evening?

Use simple {lang_word()}. Be direct and practical for Indian farmers."""

                result = ollama_chat(sym_prompt)

                # Also check keyword database for quick reference
                quick_ref = None
                for keyword, info in DISEASE_INFO.items():
                    if keyword in symptom_color.lower() or keyword in symptom_pattern.lower() or keyword in extra_desc.lower():
                        quick_ref = (keyword, info)
                        break

                st.markdown(f"""<div class='disease-alert'>
<h4>🌿 Diagnosis: {crop_s} — {symptom_color} {symptom_pattern} on {symptom_part}</h4>
<p style='font-size:0.92rem; line-height:1.7;'>{result.replace(chr(10),'<br>')}</p>
</div>""", unsafe_allow_html=True)

                if quick_ref:
                    st.markdown(f"""<div class='advice-box'>
<h4>⚡ Quick Reference: {quick_ref[0].title()}</h4>
<b>Remedy:</b> {quick_ref[1]['remedy']}<br>
<b>Prevention:</b> {quick_ref[1]['prevention']}
</div>""", unsafe_allow_html=True)

                speak(result, lang_code())

        st.markdown('</div>', unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: MULTILINGUAL TRANSLATOR
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "translator":
    st.markdown(f'<div class="hero-banner"><h1>{T("trans_title")}</h1><p>{T("trans_sub")}</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="kv-card">', unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])
    with col1:
        input_text = st.text_area("📝 Enter text to translate", height=140,
                                   placeholder="Type in English, Hindi, or any Indian language...")
    with col2:
        target_lang = st.selectbox("Translate to", list(LANG_MAP.keys()))
        st.session_state.target_lang = target_lang
        voice_output = st.checkbox("🔊 Speak translation", value=True)

    # Quick agri phrase buttons
    st.markdown("**⚡ Quick agricultural phrases:**")
    agri_phrases = [
        "Apply fertilizer before sowing",
        "Irrigate the field twice a week",
        "Spray pesticide in the morning",
        "Check soil moisture before watering",
        "Use certified seeds for better yield",
    ]
    phrase_cols = st.columns(3)
    for i, phrase in enumerate(agri_phrases):
        with phrase_cols[i % 3]:
            if st.button(phrase, key=f"phrase_{i}"):
                input_text = phrase

    if st.button(T("translate_btn")):
        if input_text:
            with st.spinner(f"Translating to {target_lang}..."):
                try:
                    target_code = LANG_MAP[target_lang]
                    translated = GoogleTranslator(source='auto', target=target_code).translate(input_text)

                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("**Original:**")
                        st.info(input_text)
                    with col_b:
                        st.markdown(f"**{target_lang} Translation:**")
                        st.success(translated)

                    if voice_output:
                        speak(translated, target_code)

                    # AI-enhanced agricultural context
                    st.markdown("---")
                    with st.expander("🤖 AI Agricultural Context (Llama 3)"):
                        context_prompt = f"""Translate this agricultural text to {target_lang} and also explain what it means for a farmer in simple words:
"{input_text}"
First give the {target_lang} translation, then a 2-sentence explanation of why this matters for farmers."""
                        ai_translation = ollama_chat(context_prompt)
                        st.write(ai_translation)

                except Exception as e:
                    st.error(f"Translation error: {e}")
        else:
            st.warning("Please enter text to translate.")

    st.markdown('</div>', unsafe_allow_html=True)

    # Language reference card
    st.markdown('<div class="kv-card">', unsafe_allow_html=True)
    st.markdown("#### 🗺️ Supported Indian Languages")
    lang_cols = st.columns(5)
    lang_flags = {
        "Hindi": "🇮🇳", "Gujarati": "🌿", "Punjabi": "🌾",
        "Marathi": "🏔️", "Bengali": "🌸", "Tamil": "🌴",
        "Telugu": "🌺", "Kannada": "🏯", "Odia": "🎨", "Urdu": "📜"
    }
    for i, (lang, flag) in enumerate(lang_flags.items()):
        with lang_cols[i % 5]:
            st.markdown(f"**{flag} {lang}**")
    st.markdown('</div>', unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: WEATHER ALERTS
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "weather":
    st.markdown(f'<div class="hero-banner"><h1>{T("weather_title")}</h1><p>{T("weather_sub")}</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="kv-card">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        state_w = st.selectbox(T("select_state"), list(INDIA_LOCATIONS.keys()))
    with c2:
        district_w = st.selectbox(T("select_district"), INDIA_LOCATIONS[state_w])

    if st.button(T("fetch_weather_btn")):
        with st.spinner(f"Fetching weather for {district_w}..."):
            lat, lon = CITY_COORDS.get(district_w, (22.3, 73.1))
            try:
                # Fetch extended forecast
                url = (f"https://api.open-meteo.com/v1/forecast?"
                       f"latitude={lat}&longitude={lon}"
                       f"&current_weather=true"
                       f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max"
                       f"&timezone=Asia%2FKolkata&forecast_days=5")
                res = requests.get(url, timeout=10)

                if res.status_code == 200:
                    data = res.json()
                    cw   = data["current_weather"]
                    temp = cw["temperature"]
                    wind = cw["windspeed"]
                    wcode = cw.get("weathercode", 0)

                    # Weather code to description
                    weather_desc = {0: "Clear sky ☀️", 1: "Mainly clear 🌤️", 2: "Partly cloudy ⛅",
                                    3: "Overcast ☁️", 45: "Foggy 🌫️", 51: "Light drizzle 🌦️",
                                    61: "Slight rain 🌧️", 71: "Slight snow ❄️", 80: "Rain showers 🌧️",
                                    95: "Thunderstorm ⛈️"}.get(wcode, "Cloudy ☁️")

                    m1, m2, m3, m4 = st.columns(4)
                    with m1:
                        st.markdown(f'<div class="metric-box"><h4>🌡️ Temp</h4><h2>{temp}°C</h2></div>', unsafe_allow_html=True)
                    with m2:
                        st.markdown(f'<div class="metric-box"><h4>💨 Wind</h4><h2>{wind}<br><small>km/h</small></h2></div>', unsafe_allow_html=True)
                    with m3:
                        daily = data.get("daily", {})
                        rain = daily.get("precipitation_sum", [0])[0] if daily else 0
                        st.markdown(f'<div class="metric-box"><h4>🌧️ Rain Today</h4><h2>{rain}<br><small>mm</small></h2></div>', unsafe_allow_html=True)
                    with m4:
                        st.markdown(f'<div class="metric-box"><h4>🌤️ Condition</h4><h2 style="font-size:1rem;">{weather_desc}</h2></div>', unsafe_allow_html=True)

                    # 5-day mini forecast
                    if "daily" in data:
                        st.markdown("#### 📅 5-Day Forecast")
                        daily = data["daily"]
                        days = ["Today", "Tomorrow", "Day 3", "Day 4", "Day 5"]
                        day_cols = st.columns(5)
                        for i in range(min(5, len(days))):
                            with day_cols[i]:
                                tmax = daily["temperature_2m_max"][i]
                                tmin = daily["temperature_2m_min"][i]
                                rain_d = daily["precipitation_sum"][i]
                                st.markdown(f"""<div style='background:#E8F5E9;border-radius:10px;padding:10px;text-align:center;font-size:0.85rem;'>
<b>{days[i]}</b><br>
🌡️ {tmin}–{tmax}°C<br>
🌧️ {rain_d}mm
</div>""", unsafe_allow_html=True)

                    # AI farming advisory
                    st.markdown("---")
                    with st.spinner("Generating AI farming advisory..."):
                        advisory_prompt = f"""A farmer in {district_w} needs a farming advisory based on this weather:
Temperature: {temp}°C, Wind: {wind} km/h, Rain: {rain}mm, Condition: {weather_desc}
Give a 3-point practical farming advisory in simple {lang_word()}:
1. What to do TODAY on the farm
2. Which crop operations to do or avoid
3. Irrigation/spray advice based on this weather"""
                        advisory = ollama_chat(advisory_prompt)

                        st.markdown(f"""<div class='advice-box'>
<h4>🤖 AI Farming Advisory for {district_w}</h4>
<p>{advisory.replace(chr(10),'<br>')}</p>
</div>""", unsafe_allow_html=True)
                        speak(advisory, lang_code())

                    # Alert banners
                    if temp > 38:
                        st.error("🔴 HEAT STRESS ALERT: Irrigate immediately. Avoid field work between 11AM–4PM. Provide shade for nurseries.")
                    elif temp > 35:
                        st.warning("⚠️ High temperature. Increase irrigation frequency. Do not spray pesticides today.")
                    elif temp < 8:
                        st.warning("❄️ Frost warning. Cover sensitive seedlings with plastic sheets. Delay transplanting.")
                    elif rain and float(rain) > 30:
                        st.warning("🌧️ Heavy rain expected. Do not irrigate. Watch for waterlogging. Ensure drainage channels are clear.")
                    else:
                        st.success(f"✅ Weather in {district_w} is suitable for normal farming operations.")

            except Exception as e:
                st.error(f"Weather fetch error: {e}. Check internet connection.")
    st.markdown('</div>', unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: MANDI PRICE TRACKER + PREDICTION
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "mandi":
    st.markdown(f'<div class="hero-banner"><h1>{T("mandi_title")}</h1><p>{T("mandi_sub")}</p></div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["💰 Current Prices", "📊 Price Prediction"])

    with tab1:
        st.markdown('<div class="kv-card">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            state_m = st.selectbox("State", list(INDIA_LOCATIONS.keys()), key="m_state")
        with c2:
            district_m = st.selectbox("District", INDIA_LOCATIONS[state_m], key="m_dist")
        with c3:
            commodity = st.selectbox("Crop / Commodity", list(BASE_PRICES.keys()))

        if st.button(T("check_rates_btn")):
            variance = random.randint(-180, 250)
            final_price = BASE_PRICES[commodity] + variance
            msp = BASE_PRICES[commodity]
            diff_from_msp = final_price - msp

            trend_icon = "▲" if variance > 0 else "▼"
            trend_color = "#166534" if variance > 0 else "#991b1b"

            st.markdown(f"""<div class='price-card'>
<h3 style='color:#334155;margin-bottom:5px;'>📍 APMC Mandi: {district_m}, {state_m}</h3>
<h1 style='color:#1B5E20;font-size:3rem;margin:10px 0;'>
    ₹{final_price:,} <span style='font-size:1.2rem;color:#64748b;'>/ Quintal</span>
</h1>
<p style='color:{trend_color};font-weight:bold;font-size:1.1rem;'>
    {trend_icon} {'Up' if variance>0 else 'Down'} by ₹{abs(variance)} from yesterday
</p>
<hr style='border-color:#e2e8f0;margin:12px 0;'>
<p style='color:#64748b;font-size:0.9rem;'>
    MSP (Min Support Price): ₹{msp:,} | 
    Difference: <span style='color:{trend_color};font-weight:600;'>
    {'+' if diff_from_msp>=0 else ''}₹{diff_from_msp:,}
    </span>
</p>
</div>""", unsafe_allow_html=True)

            # Selling advice
            with st.spinner("Generating selling advice..."):
                sell_prompt = f"""A farmer wants to sell {commodity} at ₹{final_price}/quintal in {district_m}.
MSP is ₹{msp}/quintal. Price is {'above' if diff_from_msp>0 else 'below'} MSP by ₹{abs(diff_from_msp)}.
Give a 2-sentence selling advice in simple {lang_word()}: Should they sell now or wait? Any better market nearby?"""
                advice = ollama_chat(sell_prompt)
                st.markdown(f"<div class='advice-box'><h4>💡 Selling Advice</h4><p>{advice}</p></div>", unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        st.markdown('<div class="kv-card">', unsafe_allow_html=True)
        st.markdown("#### 📊 AI Price Trend Prediction")
        pred_crop = st.selectbox("Select crop for prediction", list(BASE_PRICES.keys()), key="pred_crop")
        pred_weeks = st.slider("Predict for next N weeks", 1, 8, 4)

        if st.button(T("predict_btn")):
            with st.spinner("AI analyzing market trends..."):
                pred_prompt = f"""You are an agricultural market analyst in India. Analyze the price trend for {pred_crop} for the next {pred_weeks} weeks.
Current market price: ₹{BASE_PRICES[pred_crop]}/quintal.
Consider: seasonal demand, harvest cycles, export trends, government MSP policy, fuel prices impact on transport.
Provide:
1. PREDICTION: Will price rise, fall, or stay stable?
2. EXPECTED RANGE: ₹X to ₹Y per quintal
3. BEST TIME TO SELL: Week 1-{pred_weeks}?
4. REASON: 2 key factors driving the trend
Keep it simple for Indian farmers in {lang_word()}."""
                prediction = ollama_chat(pred_prompt)
                st.markdown(f"""<div class='advice-box'>
<h4>🔮 Price Prediction: {pred_crop} — Next {pred_weeks} Weeks</h4>
<p>{prediction.replace(chr(10),'<br>')}</p>
</div>""", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("**📞 Sell directly online:** [eNAM Portal](https://www.enam.gov.in) | Helpline: **1800-270-0224**")
        st.markdown('</div>', unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: GOVERNMENT SCHEMES
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "schemes":
    st.markdown(f'<div class="hero-banner"><h1>{T("schemes_title")}</h1><p>{T("schemes_sub")}</p></div>', unsafe_allow_html=True)

    # Check eligibility
    st.markdown('<div class="kv-card">', unsafe_allow_html=True)
    st.markdown("#### 🔍 Check Your Eligibility")
    col1, col2, col3 = st.columns(3)
    with col1:
        land_size   = st.number_input("Land holding (acres)", min_value=0.0, max_value=500.0, value=2.0, step=0.5)
    with col2:
        annual_income = st.number_input("Annual income (₹)", min_value=0, max_value=1000000, value=80000, step=5000)
    with col3:
        has_kcc     = st.selectbox("Do you have Kisan Credit Card?", ["No", "Yes"])

    if st.button(T("find_schemes_btn")):
        with st.spinner("Checking eligibility..."):
            eligibility_prompt = f"""An Indian farmer has:
- Land: {land_size} acres
- Annual income: ₹{annual_income}
- Kisan Credit Card: {has_kcc}

List which of these schemes they qualify for and why, in simple {lang_word()}:
PM-KISAN, PMFBY, Kisan Credit Card, Soil Health Card, eNAM, PM Kusum (solar pump).
For each eligible scheme, mention: benefit amount and how to apply in 1 line."""
            result = ollama_chat(eligibility_prompt)
            st.markdown(f"""<div class='advice-box'>
<h4>✅ Your Eligible Schemes</h4>
<p>{result.replace(chr(10),'<br>')}</p>
</div>""", unsafe_allow_html=True)
            speak(result, lang_code())
    st.markdown('</div>', unsafe_allow_html=True)

    # All schemes reference
    st.markdown("#### 📋 All Major Schemes — Quick Reference")
    for scheme_name, info in GOVT_SCHEMES.items():
        st.markdown(f"""<div class='scheme-card'>
<h3>🏛️ {scheme_name}</h3>
<div class='benefit'>💰 Benefit: {info['benefit']}</div>
<div class='detail'>
  👤 <b>Who can apply:</b> {info['eligibility']}<br>
  📝 <b>How to apply:</b> {info['how_to_apply']}
</div>
<span class='helpline-badge'>📞 {info['helpline']}</span>
</div>""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: CHATBOT HELPLINE
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "chatbot":
    st.markdown(f'<div class="hero-banner"><h1>{T("chatbot_title")}</h1><p>{T("chatbot_sub")}</p></div>', unsafe_allow_html=True)

    col_chat, col_faq = st.columns([2, 1])

    with col_chat:
        st.markdown('<div class="kv-card">', unsafe_allow_html=True)
        st.markdown("#### 🤖 Chat with KrishiVaani AI")

        # Display chat history
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.chat_history:
                if msg["role"] == "user":
                    st.markdown(f'<div class="chat-bubble-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="chat-bubble-bot">🌾 {msg["content"]}</div>', unsafe_allow_html=True)

        # Input area
        chat_input = st.text_input("Type your question here...",
                                    placeholder="e.g. Kisan Credit Card ke liye kaise apply karein?",
                                    key="chat_input_field")

        col_send, col_voice, col_clear = st.columns([2, 1, 1])
        with col_send:
            send_btn = st.button(T("send_btn"))
        with col_voice:
            voice_reply = st.checkbox("🔊 Voice reply", value=True)
        with col_clear:
            if st.button(T("clear_chat_btn")):
                st.session_state.chat_history = []
                st.rerun()

        if send_btn and chat_input:
            st.session_state.chat_history.append({"role": "user", "content": chat_input})

            with st.spinner("KrishiVaani is thinking..."):
                # Check FAQ database first for instant answers
                faq_answer = None
                for keyword, answer in CHATBOT_FAQS.items():
                    if keyword in chat_input.lower():
                        faq_answer = answer
                        break

                # Build conversation context
                history_text = ""
                for m in st.session_state.chat_history[-6:]:
                    role = "Farmer" if m["role"]=="user" else "KrishiVaani"
                    history_text += f"{role}: {m['content']}\n"

                chatbot_prompt = f"""You are KrishiVaani, a friendly agricultural assistant for Indian farmers.
You answer questions about farming, crops, fertilizers, government schemes, weather, and market prices.
Keep answers short (3-4 sentences), practical, and in simple {lang_word()}.
Always end with one actionable tip or a relevant helpline number.

Conversation so far:
{history_text}
KrishiVaani:"""

                bot_reply = ollama_chat(chatbot_prompt)

                # Combine FAQ reference with AI answer if relevant
                if faq_answer:
                    bot_reply = bot_reply + f"\n\n📚 Quick Reference: {faq_answer}"

                st.session_state.chat_history.append({"role": "assistant", "content": bot_reply})

                if voice_reply:
                    speak(bot_reply.split("\n\n📚")[0], lang_code())

            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with col_faq:
        st.markdown('<div class="kv-card">', unsafe_allow_html=True)
        st.markdown("#### ⚡ Quick Questions")
        quick_qs = [
            "Fertilizer kitna dena chahiye?",
            "KCC loan ke liye apply karo",
            "Pesticide kab spray karein?",
            "PM-KISAN status check karo",
            "Organic farming kaise karein?",
            "Mandi price kaise check karein?",
        ]
        for q in quick_qs:
            if st.button(f"❓ {q}", key=f"faq_{q}"):
                st.session_state.chat_history.append({"role": "user", "content": q})
                with st.spinner("Answering..."):
                    reply = ollama_chat(f"Answer this farmer question in simple {lang_word()} in 3 sentences: {q}")
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                st.rerun()

        st.markdown("---")
        st.markdown("**📞 Emergency Helplines:**")
        st.markdown("🌾 Kisan: **1800-180-1551**")
        st.markdown("🌧️ Weather: **1800-180-1717**")
        st.markdown("💊 Pesticide: **1800-200-1020**")
        st.markdown("🏛️ PM-KISAN: **155261**")
        st.markdown('</div>', unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# PAGE: DOCUMENT SUMMARIZER
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "doc_lab":
    st.markdown(f'<div class="hero-banner"><h1>{T("doc_title")}</h1><p>{T("doc_sub")}</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="kv-card">', unsafe_allow_html=True)
    up_file = st.file_uploader("📁 Upload PDF (Scheme document / Soil report / Krishi guide)", type="pdf")

    doc_type = st.selectbox("Document type", [
        "Government Scheme", "Soil Health Card", "Crop Advisory", "Insurance Policy", "Agricultural Report", "Other"
    ])

    if up_file:
        with st.spinner("Extracting text from PDF..."):
            reader = PdfReader(up_file)
            full_text = ""
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    full_text += t + "\n"

        st.success(f"✅ Document loaded — {len(full_text):,} characters across {len(reader.pages)} pages")

        col1, col2 = st.columns(2)
        with col1:
            if st.button(T("summary_btn")):
                with st.spinner("Llama 3 is reading the document..."):
                    prompt = f"""You are reading a {doc_type} document for an Indian farmer.
Summarize the most important information in exactly 5 bullet points in simple {lang_word()}.
Each bullet point should be ONE actionable sentence that a farmer can immediately understand and use.
Document text (first 4000 characters): {full_text[:4000]}"""
                    summary = ollama_chat(prompt)
                    st.markdown("### 📋 Summary")
                    st.info(summary)
                    speak(summary, lang_code())

        with col2:
            if st.button(T("extract_btn")):
                with st.spinner("Extracting important details..."):
                    prompt = f"""From this {doc_type} document, extract ONLY:
- Money amounts (₹ figures, benefits)
- Important dates and deadlines
- Eligibility criteria
- Phone numbers / websites
Format as a clean list in {lang_word()}. Document: {full_text[:3000]}"""
                    numbers = ollama_chat(prompt)
                    st.markdown("### 🔢 Key Details")
                    st.success(numbers)

        if st.button(T("translate_summary_btn")):
            with st.spinner("Translating..."):
                prompt = f"Translate this document summary to {st.session_state.target_lang} in simple farmer-friendly language: {full_text[:2000]}"
                translated_summary = ollama_chat(prompt)
                st.markdown(f"### 🌍 {st.session_state.target_lang} Summary")
                st.info(translated_summary)
                tgt_code = LANG_MAP.get(st.session_state.target_lang, "hi")
                speak(translated_summary, tgt_code)

    st.markdown('</div>', unsafe_allow_html=True)