#!/bin/bash
# تشغيل سريع لـ Gidoen على Raspberry Pi

echo "🤖 تثبيت Gidoen..."

# تحديث النظام
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv portaudio19-dev > /dev/null 2>&1

# إنشاء البيئة الافتراضية
python3 -m venv .venv
source .venv/bin/activate

# تثبيت المتطلبات
echo "⏳ تثبيت المكتبات..."
pip install --upgrade pip > /dev/null 2>&1
pip install prompt_toolkit SpeechRecognition pyttsx3 > /dev/null 2>&1

# تثبيت Ollama
if ! command -v ollama &> /dev/null; then
    echo "📥 تثبيت Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh > /dev/null 2>&1
fi

# تحميل النموذج
echo "🧠 تحميل النموذج llama3.2:3b..."
ollama pull llama3.2:3b > /dev/null 2>&1

# تثبيت الخدمة
echo "⚙️ تثبيت خدمة Gidoen..."
sudo cp gidoen.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "✓ التثبيت كامل"
echo ""
echo "لبدء Gidoen الآن:"
echo "  ollama serve &"
echo "  python3 gidoen.py"
echo ""
echo "أو للتشغيل 24/7:"
echo "  sudo systemctl enable gidoen"
echo "  sudo systemctl start gidoen"
echo "  sudo journalctl -u gidoen -f"
