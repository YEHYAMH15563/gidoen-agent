#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GIDOEN - AI Home Assistant for Raspberry Pi
محلي، آمن، 24/7 جاهز، يتعلم مهارات جديدة
"""

import json
import sqlite3
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Dict, List
import difflib
import shutil
import urllib.request

# ============================================
# CONFIGURATION
# ============================================

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR
DATA_DIR = BASE_DIR / "data"
SAFE_ROOTS = [str(BASE_DIR)]

DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "gidoen.db"

SYSTEM_PROMPT = """
أنت Gidoen، مساعد ذكي محلي لـ Raspberry Pi.
أنت مفيد وآمن وموجز.
يمكنك إدارة مهام تأتمتة المنزل والملفات والأوامر المحلية.
لا تعدل أبداً المجلدات الحساسة مثل /etc أو /boot أو /usr أو /var بدون موافقة صريحة.
اشرح العمليات الخطرة دائماً قبل تنفيذها.
استخدم الأدوات المحلية فقط.
تحدث بلطف وكن حاضراً دائماً.
"""

# ============================================
# OLLAMA LLM
# ============================================

class OllamaLocalModel:
    def __init__(self, model_name="llama3.2:3b", base_url="http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.connected = False
        self._test_connection()

    def _test_connection(self):
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                self.connected = True
                print("✓ متصل بـ Ollama بنجاح!")
        except:
            print("❌ تحذير: Ollama غير متصل. تأكد من تشغيل 'ollama serve'")
            self.connected = False

    def chat(self, messages):
        if not self.connected:
            return "❌ Ollama غير متصل. شغّل 'ollama serve' في terminal آخر"

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data["message"]["content"]
        except Exception as exc:
            return f"❌ خطأ LLM: {exc}"

# ============================================
# SKILLS SYSTEM
# ============================================

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
        if name not in self.skills:
            return f"❌ المهارة غير موجودة: {name}"
        try:
            return self.skills[name].func(payload)
        except Exception as e:
            return f"❌ خطأ في تنفيذ المهارة: {e}"

# ============================================
# HOME ASSISTANT SKILLS
# ============================================

class HomeSkills:
    def __init__(self):
        self.lights_state = {}
        self.thermostat_temp = 22
        self.music_playing = False
        self.alarm_set = None
        self.devices = {}
        self.automations = []

    def control_lights(self, payload: str) -> str:
        """التحكم بالإضاءة"""
        parts = payload.lower().strip().split()
        if not parts:
            lights_info = ", ".join([f"{k}: {'✓' if v else '✗'}" for k, v in self.lights_state.items()]) or "لا توجد إضاءات"
            return f"حالة الإضاءة الحالية:\n{lights_info}"
        
        action = parts[0]
        room = " ".join(parts[1:]) if len(parts) > 1 else "غرفة المعيشة"
        
        if action == "on":
            self.lights_state[room] = True
            return f"✓ تم تشغيل إضاءة {room}"
        elif action == "off":
            self.lights_state[room] = False
            return f"✓ تم إطفاء إضاءة {room}"
        else:
            return f"استخدم: lights on/off <room>"

    def control_thermostat(self, payload: str) -> str:
        """التحكم بدرجة الحرارة"""
        parts = payload.strip().split()
        if not parts:
            return f"درجة الحرارة الحالية: {self.thermostat_temp}°C"
        
        try:
            temp = int(parts[0])
            if 15 <= temp <= 35:
                self.thermostat_temp = temp
                return f"✓ تم ضبط درجة الحرارة على {temp}°C"
            else:
                return "درجة الحرارة يجب أن تكون بين 15 و 35 درجة مئوية"
        except:
            return f"❌ أدخل درجة حرارة صحيحة (أرقام فقط)"

    def control_music(self, payload: str) -> str:
        """تشغيل الموسيقى"""
        cmd = payload.lower().strip()
        if cmd == "play":
            self.music_playing = True
            return "▶ تم بدء التشغيل 🎵"
        elif cmd == "pause":
            self.music_playing = False
            return "⏸ تم إيقاف التشغيل"
        else:
            status = "تشغيل 🎵" if self.music_playing else "متوقف"
            return f"الموسيقى حالياً: {status}"

    def set_alarm(self, payload: str) -> str:
        """ضبط المنبهات"""
        if not payload.strip():
            return f"المنبه الحالي: {self.alarm_set or 'لم يتم ضبطه'}"
        self.alarm_set = payload.strip()
        return f"✓ تم ضبط المنبه على {self.alarm_set} ⏰"

    def weather_info(self, payload: str) -> str:
        """معلومات الطقس المحلية"""
        return "☀️ الطقس اليوم:\n- درجة الحرارة: 25°C\n- الرطوبة: 60%\n- الحالة: مشمس 🌞"

    def system_status(self, payload: str) -> str:
        """حالة النظام الكاملة"""
        lights_status = ", ".join([f"{k}: {'✓' if v else '✗'}" for k, v in self.lights_state.items()]) or "لا توجد"
        music_status = "تشغيل 🎵" if self.music_playing else "متوقف"
        
        return f"""
╔════════════════════════════════════════╗
║       📊 حالة النظام - System Status    ║
╠════════════════════════════════════════╣
║ 🤖 Gidoen Status:     نشط وجاهز ✓     ║
║ 🧠 AI Model:          llama3.2:3b      ║
║ 📍 الموقع:            {BASE_DIR}
║ ──────────────────────────────────────  ║
║ 💡 الإضاءة:           {lights_status}
║ 🌡️  درجة الحرارة:      {self.thermostat_temp}°C      ║
║ 🎵 الموسيقى:          {music_status}
║ ⏰ المنبه:            {self.alarm_set or 'لم يتم ضبطه'}
║ 🔄 الأتمتة:           {len(self.automations)} مهمة
╚════════════════════════════════════════╝
"""

    def list_devices(self, payload: str) -> str:
        """قائمة الأجهزة المتاحة"""
        devices = [
            "💡 lights - التحكم بالإضاءة (on/off <room>)",
            "🌡️  thermostat - التحكم بالحرارة (<temp>)",
            "🎵 music - تشغيل الموسيقى (play/pause)",
            "⏰ alarm - ضبط المنبهات (<time>)",
            "☀️  weather - معلومات الطقس",
            "📊 status - حالة النظام",
            "🔄 automation - جدولة مهام",
            "📱 devices - قائمة الأجهزة"
        ]
        return "الأجهزة المتاحة:\n" + "\n".join(devices)

    def automation_task(self, payload: str) -> str:
        """جدولة مهام أتمتة"""
        if not payload.strip():
            return f"المهام المجدولة: {len(self.automations)}\n" + "\n".join(self.automations)
        task = payload.strip()
        self.automations.append(task)
        return f"✓ تم جدولة المهمة: {task}"

    def system_command(self, payload: str) -> str:
        """تنفيذ أوامر النظام الآمنة"""
        cmd = payload.lower().strip()
        if cmd == "disk":
            try:
                result = subprocess.run(["df", "-h"], capture_output=True, text=True)
                return result.stdout[:500]
            except:
                return "❌ لا يمكن الحصول على معلومات القرص"
        elif cmd == "memory":
            try:
                result = subprocess.run(["free", "-h"], capture_output=True, text=True)
                return result.stdout[:500]
            except:
                return "❌ لا يمكن الحصول على معلومات الذاكرة"
        elif cmd == "processes":
            try:
                result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
                return result.stdout[:500]
            except:
                return "❌ لا يمكن الحصول على قائمة العمليات"
        else:
            return "أوامر متاحة: disk, memory, processes"

# ============================================
# SAFE FILE OPERATIONS
# ============================================

def _is_safe_path(path: str) -> bool:
    """التحقق من أن المسار آمن"""
    p = Path(path).resolve()
    for root in SAFE_ROOTS:
        root_path = Path(root).resolve()
        try:
            p.relative_to(root_path)
            return True
        except ValueError:
            pass
    return False

def read_file(path: str) -> str:
    """قراءة ملف بأمان"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"الملف غير موجود: {path}")
    if not _is_safe_path(str(p)):
        raise PermissionError(f"المسار غير مسموح: {path}")
    return p.read_text(encoding="utf-8")

def write_file(path: str, content: str) -> str:
    """كتابة ملف بأمان مع عمل نسخة احتياطية"""
    p = Path(path)
    if not _is_safe_path(str(p)):
        raise PermissionError(f"المسار غير مسموح: {path}")

    old = p.read_text(encoding="utf-8") if p.exists() else ""
    diff = "".join(difflib.unified_diff(
        old.splitlines(True),
        content.splitlines(True),
        fromfile="قبل",
        tofile="بعد",
        lineterm=""
    ))

    backup = p.with_suffix(p.suffix + ".bak")
    if p.exists():
        shutil.copy2(p, backup)
        print(f"✓ تم حفظ نسخة احتياطية: {backup}")

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

    return diff if diff else "لا توجد تغييرات في المحتوى."

def list_files(path: str = ".") -> str:
    """عرض قائمة الملفات"""
    p = Path(path)
    if not _is_safe_path(str(p)):
        return f"❌ المسار غير مسموح: {path}"
    if not p.exists():
        return f"❌ المسار غير موجود: {path}"
    
    files = list(p.iterdir())[:50]
    return "\n".join([f"{'📁' if f.is_dir() else '📄'} {f.name}" for f in files])

# ============================================
# DATABASE - MEMORY & HISTORY
# ============================================

class GidoenMemory:
    """نظام الذاكرة والتاريخ"""
    def __init__(self):
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS code_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                old_content TEXT,
                new_content TEXT,
                status TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def save_chat(self, role: str, content: str):
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", (role, content))
        conn.commit()
        conn.close()

    def get_history(self, limit: int = 10) -> List:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        history = cur.fetchall()
        conn.close()
        return list(reversed(history))

    def log_skill(self, skill_name: str, payload: str, result: str):
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("INSERT INTO skills_log (skill_name, payload, result) VALUES (?, ?, ?)",
                    (skill_name, payload, result))
        conn.commit()
        conn.close()

    def log_code_change(self, file_path: str, old_content: str, new_content: str, status: str = "pending"):
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("INSERT INTO code_changes (file_path, old_content, new_content, status) VALUES (?, ?, ?, ?)",
                    (file_path, old_content, new_content, status))
        conn.commit()
        conn.close()

# ============================================
# AGENT CORE
# ============================================

class GidoenAgent:
    """محرك Gidoen الأساسي"""
    def __init__(self, model: OllamaLocalModel, skills: SkillRegistry, memory: GidoenMemory):
        self.model = model
        self.skills = skills
        self.memory = memory
        self.history = []

    def chat(self, user_message: str) -> str:
        """معالجة الرسالة"""
        self.history.append({"role": "user", "content": user_message})
        self.memory.save_chat("user", user_message)

        low = user_message.strip().lower()

        # SKILL COMMAND
        if low.startswith("skill "):
            name = user_message[6:].strip()
            result = self.skills.run(name, "")
            self.memory.log_skill(name, "", result)
            return result

        # READ FILE
        if low.startswith("read "):
            path = user_message[5:].strip()
            try:
                content = read_file(path)
                return content[:2000]
            except Exception as exc:
                return f"❌ خطأ: {exc}"

        # WRITE FILE
        if low.startswith("write "):
            try:
                payload = user_message[6:].strip()
                if "->" not in payload:
                    return "استخدم الصيغة: write <path> -> <content>"
                file_path, content = payload.split("->", 1)
                diff = write_file(file_path.strip(), content.strip())
                self.memory.log_code_change(file_path.strip(), "", content.strip(), "applied")
                return f"✓ تم تحديث الملف\n{diff}"
            except Exception as exc:
                return f"❌ خطأ: {exc}"

        # LIST FILES
        if low.startswith("list "):
            path = user_message[5:].strip() or "."
            return list_files(path)

        # LLM CHAT
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in self.history[-10:]:
            messages.append({"role": item["role"], "content": item["content"]})

        reply = self.model.chat(messages)
        self.history.append({"role": "assistant", "content": reply})
        self.memory.save_chat("assistant", reply)
        return reply

# ============================================
# TERMINAL UI
# ============================================

try:
    from prompt_toolkit import prompt
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.styles import Style
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

class TerminalUI:
    """واجهة المستخدم في التيرمنال"""
    def __init__(self):
        self.model = OllamaLocalModel("llama3.2:3b")
        self.skills = SkillRegistry()
        self.home = HomeSkills()
        self.memory = GidoenMemory()

        # تسجيل المهارات
        self.skills.register(Skill("lights", "💡 التحكم بالإضاءة", lambda p: self.home.control_lights(p)))
        self.skills.register(Skill("thermostat", "🌡️ التحكم بالحرارة", lambda p: self.home.control_thermostat(p)))
        self.skills.register(Skill("music", "🎵 تشغيل الموسيقى", lambda p: self.home.control_music(p)))
        self.skills.register(Skill("alarm", "⏰ ضبط المنبهات", lambda p: self.home.set_alarm(p)))
        self.skills.register(Skill("weather", "☀️ معلومات الطقس", lambda p: self.home.weather_info(p)))
        self.skills.register(Skill("status", "📊 حالة النظام", lambda p: self.home.system_status(p)))
        self.skills.register(Skill("devices", "📱 قائمة الأجهزة", lambda p: self.home.list_devices(p)))
        self.skills.register(Skill("automation", "🔄 مهام الأتمتة", lambda p: self.home.automation_task(p)))
        self.skills.register(Skill("system", "🖥️ أوامر النظام", lambda p: self.home.system_command(p)))

        self.agent = GidoenAgent(self.model, self.skills, self.memory)

    def run(self):
        """تشغيل الواجهة"""
        self._print_banner()

        if HAS_PROMPT_TOOLKIT:
            self._run_with_prompt_toolkit()
        else:
            self._run_simple()

    def _print_banner(self):
        """طباعة البانر الترحيبي"""
        print("""
╔══════════════════════════════════════════════════╗
║                                                  ║
║       🤖 GIDOEN AI HOME ASSISTANT 🤖           ║
║                                                  ║
║     وكيل ذكي محلي لـ Raspberry Pi               ║
║     Local AI Assistant for Smart Home           ║
║                                                  ║
║  💡 مهارات ذكية | 🏠 أتمتة المنزل                 ║
║  ✓ آمن وخصوصي | 🔒 بدون انترنت                  ║
║                                                  ║
║  اكتب 'help' للمساعدة | Type 'exit' to quit     ║
║                                                  ║
╚══════════════════════════════════════════════════╝
""")

    def _run_with_prompt_toolkit(self):
        """تشغيل مع prompt_toolkit (أفضل تجربة)"""
        style = Style.from_dict({"": "ansigreen bold"})
        completer = WordCompleter([
            "help", "status", "skill list", "lights", "thermostat",
            "music", "alarm", "weather", "devices", "automation", "system",
            "chat", "read", "write", "list", "history", "exit"
        ], ignore_case=True)

        while True:
            try:
                raw = prompt("\n🤖 gidoen> ", completer=completer, style=style)
            except KeyboardInterrupt:
                print("\n\n👋 وداعاً! (Goodbye!)")
                break
            except EOFError:
                print("\n\n👋 وداعاً! (Goodbye!)")
                break

            if not raw.strip():
                continue

            self._process_command(raw)

    def _run_simple(self):
        """تشغيل بسيط بدون prompt_toolkit"""
        print("⚠️  تثبيت prompt_toolkit يعطي تجربة أفضل: pip install prompt_toolkit")
        while True:
            try:
                raw = input("\n🤖 gidoen> ")
            except KeyboardInterrupt:
                print("\n\n👋 وداعاً! (Goodbye!)")
                break
            except EOFError:
                print("\n\n👋 وداعاً! (Goodbye!)")
                break

            if not raw.strip():
                continue

            self._process_command(raw)

    def _process_command(self, raw: str):
        """معالجة الأمر"""
        cmd = raw.strip().lower()

        if cmd in ("exit", "quit"):
            print("👋 وداعاً! (Goodbye!)")
            sys.exit(0)

        if cmd == "help":
            self._print_help()
            return

        if cmd == "status":
            print(self.skills.run("status", ""))
            return

        if cmd == "skill list":
            skills = self.skills.list_skills()
            print("\n📚 المهارات المتاحة:")
            for i, s in enumerate(skills, 1):
                print(f"  {i}. {s}")
            return

        if cmd == "history":
            history = self.memory.get_history(10)
            print("\n📜 السجل:")
            for role, content in history:
                role_icon = "👤" if role == "user" else "🤖"
                print(f"{role_icon} {role}: {content[:100]}")
            return

        if cmd.startswith("lights "):
            print(self.skills.run("lights", raw[7:]))
            return

        if cmd.startswith("thermostat "):
            print(self.skills.run("thermostat", raw[11:]))
            return

        if cmd.startswith("music "):
            print(self.skills.run("music", raw[6:]))
            return

        if cmd.startswith("alarm "):
            print(self.skills.run("alarm", raw[6:]))
            return

        if cmd == "weather":
            print(self.skills.run("weather", ""))
            return

        if cmd == "devices":
            print(self.skills.run("devices", ""))
            return

        if cmd.startswith("automation "):
            print(self.skills.run("automation", raw[11:]))
            return

        if cmd.startswith("system "):
            print(self.skills.run("system", raw[7:]))
            return

        if cmd.startswith("read "):
            path = raw[5:].strip()
            try:
                content = read_file(path)
                print(f"\n📄 محتوى {path}:\n{content[:1000]}")
            except Exception as exc:
                print(f"❌ خطأ: {exc}")
            return

        if cmd.startswith("write "):
            payload = raw[6:].strip()
            try:
                if "->" not in payload:
                    print("❌ استخدم الصيغة: write <path> -> <content>")
                    return
                path, content = payload.split("->", 1)
                diff = write_file(path.strip(), content.strip())
                print(f"✓ تم التحديث\n{diff}")
            except Exception as exc:
                print(f"❌ خطأ: {exc}")
            return

        if cmd.startswith("list "):
            path = raw[5:].strip() or "."
            print(list_files(path))
            return

        if cmd.startswith("chat "):
            text = raw[5:].strip()
            print(f"\n🤖 Gidoen:\n{self.agent.chat(text)}")
            return

        # DEFAULT: LLM CHAT
        print(f"\n🤖 Gidoen:\n{self.agent.chat(raw)}")

    def _print_help(self):
        """طباعة المساعدة"""
        print("""
╔════════════════════════════════════════════════════╗
║            📚 Gidoen Commands - أوامر جيدوين       ║
╠════════════════════════════════════════════════════╣
║                                                    ║
║  💡 الإضاءة:                                      ║
║     lights on <room>    - تشغيل الإضاءة          ║
║     lights off <room>   - إطفاء الإضاءة          ║
║                                                    ║
║  🌡️  الحرارة:                                     ║
║     thermostat <temp>   - ضبط درجة الحرارة       ║
║     thermostat          - عرض الحالية             ║
║                                                    ║
║  🎵 الموسيقى:                                     ║
║     music play          - بدء التشغيل             ║
║     music pause         - إيقاف التشغيل           ║
║                                                    ║
║  ⏰ المنبهات:                                     ║
║     alarm <time>        - ضبط منبه                ║
║                                                    ║
║  ☀️  الطقس:                                       ║
║     weather             - معلومات الطقس           ║
║                                                    ║
║  📊 النظام:                                       ║
║     status              - حالة النظام الكاملة     ║
║     devices             - قائمة الأجهزة           ║
║     system disk         - معلومات القرص           ║
║                                                    ║
║  🔄 الأتمتة:                                      ║
║     automation <task>   - جدولة مهمة              ║
║                                                    ║
║  📁 الملفات:                                      ║
║     read <path>         - قراءة ملف               ║
║     write <path> -> <content> - كتابة ملف         ║
║     list <path>         - عرض الملفات             ║
║                                                    ║
║  💬 أخرى:                                         ║
║     chat <message>      - محادثة عادية            ║
║     history             - السجل                   ║
║     skill list          - قائمة المهارات          ║
║     help                - هذه الرسالة              ║
║     exit                - الخروج                  ║
║                                                    ║
║  💡 نصيحة: يمكنك كتابة أي شيء، سيرد Gidoen      ║
║                                                    ║
╚════════════════════════════════════════════════════╝
""")

# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    print("⏳ جاري تحميل Gidoen...")
    ui = TerminalUI()
    ui.run()
