# 🌾 KrishiVaani AI: Multilingual Farmer Assistant

KrishiVaani is a locally hosted, privacy-first AI assistant designed for Indian farmers. It leverages **Llama 3** for agricultural intelligence and supports multiple regional languages.

## 🚀 Features
* **🎙️ Smart Agri-Advisor:** Voice-to-Text support for regional languages (Hindi, Gujarati, Punjabi).
* **🍃 Disease Detector:** Diagnosis via leaf image analysis and symptom description.
* **📈 Mandi Tracker:** Real-time APMC price tracking and AI-driven price predictions.
* **☁️ Weather Advisory:** Hyper-local weather alerts with specific farming actions.
* **📜 Doc Summarizer:** Simplifies complex government scheme PDFs into simple regional language points.

## 🛠️ Tech Stack
* **Language Model:** Llama 3 (via Ollama)
* **Frontend:** Streamlit
* **Libraries:** SpeechRecognition, gTTS, PyPDF2, Deep-Translator

## 📂 Installation
1. Install [Ollama](https://ollama.com/) and run `ollama pull llama3`.
2. Clone the repo and install requirements:
   ```bash
   pip install -r requirements.txt
