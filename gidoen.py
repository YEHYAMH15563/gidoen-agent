#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gidoen - Local AI Assistant for Raspberry Pi

Features:
- Local offline AI via Ollama
- Home assistant-like skills
- Safe file access inside project root only
- Voice support if installed
- Auto health check / repair suggestions at startup
"""

import json
import sqlite3
import subprocess
import sys
import time
import shutil
import urllib.request
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List

try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

try:
    import pyttsx3
    HAS_TTS = True
except Exception:
    HAS_TTS = False

try:
    from prompt_toolkit import prompt
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.styles import Style
    HAS_PROMPT_TOOLKIT = True
except Exception:
    HAS_PROMPT_TOOLKIT = False

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "gidoen.db"
SAFE_ROOTS = [str(BASE_DIR)]

SYSTEM_PROMPT = """
أنت Gidoen، مساعد ذكي محلي لـ Raspberry Pi.
أنت مفيد وآمن وموجز.
يمكنك إدارة مهام المنزل والملفات والأوامر المحلية داخل النطاق الآمن.
لا تعدل /etc /boot /usr /var بدون موافقة صريحة.
استخدم الأدوات المحلية فقط.
"""

REQUIRED_PACKAGES = [
    "ollama",
    "prompt_toolkit",
    "SpeechRecognition",
    "pyttsx3",
]


class Doctor:
    """Performs startup checks and can repair common problems."""

    def __init__(self):
        self.issues = []

    def check_python(self):
        if sys.version_info < (3, 10):
            self.issues.append("Python 3.10+ مطلوب")

    def check_ollama_cli(self):
        if shutil.which("ollama") is None:
            self.issues.append("Ollama غير مثبت. شغّل: curl -fsSL https://ollama.com/install.sh | sh")
        else:
            try:
                out = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=False)
                if out.returncode != 0:
                    self.issues.append("Ollama موجود لكن لا يعمل بشكل صحيح")
            except Exception:
                self.issues.append("تعذر تشغيل Ollama من سطر الأوامر")

    def check_ollama_model(self):
        try:
            out = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False)
            if out.returncode == 0 and "llama3.2:3b" not in out.stdout:
                self.issues.append("النموذج llama3.2:3b غير موجود. شغّل: ollama pull llama3.2:3b")
        except Exception:
            self.issues.append("تعذر التحقق من وجود النموذج llama3.2:3b")

    def check_python_packages(self):
        missing = []
        for pkg in ["prompt_toolkit", "SpeechRecognition", "pyttsx3"]:
            try:
                __import__(pkg)
            except Exception:
                missing.append(pkg)
        if missing:
            self.issues.append("الحزم المفقودة: " + ", ".join(missing) + " | pip install " + " ".join(missing))

    def auto_fix(self):
        missing = []
        for pkg in ["prompt_toolkit", "SpeechRecognition", "pyttsx3"]:
            try:
                __import__(pkg)
            except Exception:
                missing.append(pkg)

        if missing:
            try:
                print("🔧 محاولة تثبيت الحزم المفقودة...")
                subprocess.run([sys.executable, "-m", "pip", "install", *missing], check=True)
                print("✓ تم تثبيت الحزم المفقودة")
            except Exception as e:
                print(f"❌ فشل تثبيت الحزم تلقائياً: {e}")
                print("استخدم يدويًا: python -m pip install " + " ".join(missing))

        if shutil.which("ollama") is None:
            print("⚠️ Ollama غير مثبت. تثبيته مطلوب قبل التشغيل")
            print("curl -fsSL https://ollama.com/install.sh | sh")

    def run(self):
        self.check_python()
        self.check_ollama_cli()
        self.check_ollama_model()
        self.check_python_packages()

        if self.issues:
            print("\n⚠️ مشاكل تم اكتشافها في التشغيل:")
            for problem in self.issues:
                print(" -", problem)
            print("\n🔧 محاولة الإصلاح التلقائي...")
            self.auto_fix()
            print("\nإذا استمرت المشكلة، استخدم الأوامر المذكورة أعلاه يدويًا.")
            return False

        print("✓ كل شيء يبدو جاهزًا")
        return True


class VoiceEngine:
    def __init__(self):
        self.tts_engine = None
        self.recognizer = None
        self.microphone = None
        self._init_tts()
        self._init_stt()

    def _init_tts(self):
        if not HAS_TTS:
            return
        try:
            self.tts_engine = pyttsx3.init()
            self.tts_engine.setProperty("rate", 150)
            self.tts_engine.setProperty("volume", 1.0)
        except Exception:
            self.tts_engine = None

    def _init_stt(self):
        if not HAS_SR:
            return
        try:
            self.recognizer = sr.Recognizer()
            self.microphone = sr.Microphone()
        except Exception:
            self.recognizer = None
            self.microphone = None

    def speak(self, text: str):
        if not self.tts_engine:
            print(f"🔊 {text}")
            return
        try:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception:
            print(f"🔊 {text}")

    def listen(self, timeout: int = 10) -> str:
        if not self.recognizer or not self.microphone:
            return ""
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                print("🎤 أستمع...")
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=8)
            try:
                return self.recognizer.recognize_google(audio, language="ar-SA")
            except Exception:
                try:
                    return self.recognizer.recognize_google(audio, language="en-US")
                except Exception:
                    return ""
        except Exception:
            return ""


class OllamaClient:
    def __init__(self, model_name: str = "llama3.2:3b", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.connected = False
        self.check_connection()

    def check_connection(self):
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                self.connected = True
        except Exception:
            self.connected = False

    def chat(self, messages: List[dict]) -> str:
        if not self.connected:
            return "❌ Ollama غير متصل. شغّل: ollama serve"
        payload = {"model": self.model_name, "messages": messages, "stream": False}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("message", {}).get("content", "")
        except Exception as exc:
            return f"❌ خطأ في النموذج: {exc}"


@dataclass
class Skill:
    name: str
    description: str
    func: Callable[[str], str]
    requires_approval: bool = False


class SkillRegistry:
    def __init__(self):
        self.skills: Dict[str, Skill] = {}

    def register(self, skill: Skill):
        self.skills[skill.name] = skill

    def list_skills(self):
        return sorted(self.skills.keys())

    def run(self, name: str, payload: str = "") -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"❌ المهارة غير موجودة: {name}"
        try:
            return skill.func(payload)
        except Exception as exc:
            return f"❌ خطأ في المهارة: {exc}"


class HomeSkills:
    def __init__(self):
        self.lights = {}
        self.temperature = 22
        self.music_playing = False
        self.alarm = None
        self.automations = []

    def lights_skill(self, payload: str) -> str:
        parts = payload.strip().split()
        if not parts:
            summary = ", ".join(f"{k}: {'ON' if v else 'OFF'}" for k, v in self.lights.items()) or "لا توجد إضاءات"
            return f"حالة الإضاءة:\n{summary}"
        action = parts[0].lower()
        room = " ".join(parts[1:]) if len(parts) > 1 else "الغرفة الرئيسية"
        if action == "on":
            self.lights[room] = True
            return f"✓ تم تشغيل إضاءة {room}"
        if action == "off":
            self.lights[room] = False
            return f"✓ تم إطفاء إضاءة {room}"
        return "استخدم: lights on <room> أو lights off <room>"

    def thermostat_skill(self, payload: str) -> str:
        if not payload.strip():
            return f"درجة الحرارة الحالية: {self.temperature}°C"
        try:
            temp = int(payload.strip())
            if 15 <= temp <= 35:
                self.temperature = temp
                return f"✓ تم ضبط الحرارة على {temp}°C"
            return "درجة الحرارة يجب أن تكون بين 15 و 35"
        except ValueError:
            return "أدخل رقم صحيح فقط"

    def music_skill(self, payload: str) -> str:
        cmd = payload.strip().lower()
        if cmd == "play":
            self.music_playing = True
            return "▶ تم تشغيل الموسيقى"
        if cmd == "pause":
            self.music_playing = False
            return "⏸ تم إيقاف الموسيقى"
        status = "تشغيل" if self.music_playing else "متوقف"
        return f"الموسيقى الآن: {status}"

    def alarm_skill(self, payload: str) -> str:
        if not payload.strip():
            return f"المنبه الحالي: {self.alarm or 'لم يتم ضبطه'}"
        self.alarm = payload.strip()
        return f"✓ تم ضبط المنبه على {self.alarm}"

    def weather_skill(self, payload: str) -> str:
        return "☀️ الطقس: مشمس، 25°C، رطوبة 60%"

    def status_skill(self, payload: str) -> str:
        state = ", ".join(f"{k}: {'ON' if v else 'OFF'}" for k, v in self.lights.items()) or "لا توجد"
        return (
            f"حالة Gidoen:\n"
            f"- الإضاءة: {state}\n"
            f"- الحرارة: {self.temperature}°C\n"
            f"- الموسيقى: {'تشغيل' if self.music_playing else 'متوقف'}\n"
            f"- المنبه: {self.alarm or 'غير مضبوط'}"
        )

    def automation_skill(self, payload: str) -> str:
        if not payload.strip():
            return "مهام مجدولة: " + (", ".join(self.automations) if self.automations else "لا توجد")
        self.automations.append(payload.strip())
        return f"✓ تم جدولة المهمة: {payload.strip()}"

    def system_skill(self, payload: str) -> str:
        cmd = payload.strip().lower()
        if cmd == "disk":
            try:
                out = subprocess.run(["df", "-h"], capture_output=True, text=True, check=False)
                return out.stdout[:500]
            except Exception:
                return "تعذر قراءة معلومات القرص"
        if cmd == "memory":
            try:
                out = subprocess.run(["free", "-h"], capture_output=True, text=True, check=False)
                return out.stdout[:500]
            except Exception:
                return "تعذر قراءة الذاكرة"
        return "أوامر النظام المتاحة: disk، memory"


class SafeManager:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def is_safe(self, path: str) -> bool:
        candidate = Path(path).resolve()
        try:
            candidate.relative_to(self.root)
            return True
        except ValueError:
            return False

    def read(self, path: str) -> str:
        p = Path(path)
        if not self.is_safe(str(p)):
            raise PermissionError(f"المسار غير مسموح: {path}")
        return p.read_text(encoding="utf-8")

    def write(self, path: str, content: str) -> str:
        p = Path(path)
        if not self.is_safe(str(p)):
            raise PermissionError(f"المسار غير مسموح: {path}")
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), fromfile="before", tofile="after"))
        backup = p.with_suffix(p.suffix + ".bak")
        if p.exists():
            shutil.copy2(p, backup)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return diff if diff else "لا توجد تغييرات"


class GidoenMemory:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                is_voice INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skills_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT,
                payload TEXT,
                result TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def save_chat(self, role: str, content: str, is_voice: bool = False):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO chat_history (role, content, is_voice) VALUES (?, ?, ?)", (role, content, int(is_voice)))
        conn.commit()
        conn.close()

    def log_skill(self, skill_name: str, payload: str, result: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO skills_log (skill_name, payload, result) VALUES (?, ?, ?)", (skill_name, payload, result))
        conn.commit()
        conn.close()

    def history(self, limit: int = 10):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return list(reversed(rows))


class GidoenAgent:
    def __init__(self, llm: OllamaClient, registry: SkillRegistry, memory: GidoenMemory, safe_manager: SafeManager, voice: VoiceEngine):
        self.llm = llm
        self.registry = registry
        self.memory = memory
        self.safe_manager = safe_manager
        self.voice = voice
        self.history: List[dict] = []

    def _run_command(self, user_message: str) -> str | None:
        low = user_message.strip().lower()
        if low.startswith("skill "):
            name = user_message[6:].strip()
            result = self.registry.run(name, "")
            self.memory.log_skill(name, "", result)
            return result
        if low.startswith("read "):
            path = user_message[5:].strip()
            try:
                return self.safe_manager.read(path)[:2000]
            except Exception as exc:
                return f"❌ خطأ: {exc}"
        if low.startswith("write "):
            payload = user_message[6:].strip()
            if "->" not in payload:
                return "استخدم: write <path> -> <content>"
            path, content = payload.split("->", 1)
            try:
                result = self.safe_manager.write(path.strip(), content.strip())
                return f"✓ تم التحديث\n{result}"
            except Exception as exc:
                return f"❌ خطأ: {exc}"
        if low.startswith("list "):
            path = user_message[5:].strip() or "."
            try:
                entries = [p.name for p in Path(path).iterdir()][:50]
                return "\n".join(entries)
            except Exception as exc:
                return f"❌ خطأ: {exc}"
        return None

    def chat(self, user_message: str, is_voice: bool = False) -> str:
        self.memory.save_chat("user", user_message, is_voice)
        self.history.append({"role": "user", "content": user_message})

        cmd_result = self._run_command(user_message)
        if cmd_result is not None:
            self.memory.save_chat("assistant", cmd_result, False)
            return cmd_result

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in self.history[-10:]:
            messages.append({"role": item["role"], "content": item["content"]})

        reply = self.llm.chat(messages)
        self.history.append({"role": "assistant", "content": reply})
        self.memory.save_chat("assistant", reply, False)
        return reply


class TerminalUI:
    def __init__(self):
        self.doctor = Doctor()
        self.voice = VoiceEngine()
        self.llm = OllamaClient()
        self.registry = SkillRegistry()
        self.home = HomeSkills()
        self.memory = GidoenMemory()
        self.safe_manager = SafeManager(str(BASE_DIR))

        self.registry.register(Skill("lights", "تحكم الإضاءة", lambda p: self.home.lights_skill(p)))
        self.registry.register(Skill("thermostat", "تحكم الحرارة", lambda p: self.home.thermostat_skill(p)))
        self.registry.register(Skill("music", "الموسيقى", lambda p: self.home.music_skill(p)))
        self.registry.register(Skill("alarm", "المنبه", lambda p: self.home.alarm_skill(p)))
        self.registry.register(Skill("weather", "الطقس", lambda p: self.home.weather_skill(p)))
        self.registry.register(Skill("status", "حالة النظام", lambda p: self.home.status_skill(p)))
        self.registry.register(Skill("automation", "الأتمتة", lambda p: self.home.automation_skill(p)))
        self.registry.register(Skill("system", "أوامر النظام", lambda p: self.home.system_skill(p)))

        self.agent = GidoenAgent(self.llm, self.registry, self.memory, self.safe_manager, self.voice)

    def help_text(self) -> str:
        return """
أوامر Gidoen:
- help
- status
- weather
- lights on kitchen
- lights off kitchen
- thermostat 25
- music play / pause
- alarm 07:30
- automation "مهمة"
- system disk / memory
- read <path>
- write <path> -> <content>
- chat <message>
- voice
- listen
- exit
"""

    def process(self, raw: str, from_voice: bool = False):
        cmd = raw.strip().lower()
        if cmd in ("exit", "quit"):
            print("وداعاً")
            raise SystemExit

        if cmd == "help":
            print(self.help_text())
            return

        if cmd == "voice":
            print("🎤 تم تفعيل الوضع الصوتي")
            if self.voice.tts_engine:
                self.voice.speak("تم تفعيل الوضع الصوتي")
            return

        if cmd == "listen":
            text = self.voice.listen(timeout=10)
            if not text:
                print("❌ لم أستطع فهم الكلام")
                return
            print(f"👤 فهمت: {text}")
            self.process(text, from_voice=True)
            return

        if cmd == "status":
            result = self.registry.run("status")
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd == "skill list":
            out = ", ".join(self.registry.list_skills())
            print(out)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(out)
            return

        if cmd.startswith("lights "):
            result = self.registry.run("lights", raw[7:].strip())
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd.startswith("thermostat "):
            result = self.registry.run("thermostat", raw[11:].strip())
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd.startswith("music "):
            result = self.registry.run("music", raw[6:].strip())
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd.startswith("alarm "):
            result = self.registry.run("alarm", raw[6:].strip())
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd == "weather":
            result = self.registry.run("weather", "")
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd.startswith("automation "):
            result = self.registry.run("automation", raw[11:].strip())
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd.startswith("system "):
            result = self.registry.run("system", raw[7:].strip())
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result)
            return

        if cmd.startswith("read "):
            path = raw[5:].strip()
            try:
                content = self.safe_manager.read(path)
                print(content[:1200])
            except Exception as exc:
                print(f"❌ خطأ: {exc}")
            return

        if cmd.startswith("write "):
            payload = raw[6:].strip()
            if "->" not in payload:
                print("استخدم: write <path> -> <content>")
                return
            path, content = payload.split("->", 1)
            try:
                diff = self.safe_manager.write(path.strip(), content.strip())
                print(f"✓ تم التحديث\n{diff}")
            except Exception as exc:
                print(f"❌ خطأ: {exc}")
            return

        if cmd.startswith("chat "):
            result = self.agent.chat(raw[5:].strip(), is_voice=from_voice)
            print(result)
            if from_voice and self.voice.tts_engine:
                self.voice.speak(result[:220])
            return

        result = self.agent.chat(raw, is_voice=from_voice)
        print(result)
        if from_voice and self.voice.tts_engine:
            self.voice.speak(result[:220])

    def run(self):
        print("⏳ فحص النظام قبل التشغيل...")
        ok = self.doctor.run()
        if not ok:
            print("\n⚠️ التشغيل سيستمر لكن قد تحتاج إلى إعادة التشغيل بعد الإصلاح")

        print("\nGidoen جاهز")
        print("اكتب help أو voice أو listen")

        while True:
            try:
                raw = input("gidoen> ")
            except KeyboardInterrupt:
                print("\nوداعاً")
                break
            except EOFError:
                print("\nوداعاً")
                break
            self.process(raw)


if __name__ == "__main__":
    ui = TerminalUI()
    ui.run()
