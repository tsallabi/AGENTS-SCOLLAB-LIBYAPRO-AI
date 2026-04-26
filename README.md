# Agents Collab + Manus Edition 🤖✦
### من LibyaPro AI — نسخة Manus الحصرية

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> **خمسة عقول. إجماع واحد. أفضل من أي نموذج منفرد.**

هذه النسخة الحصرية من **Agents Collab** تضيف **وكيل Manus** كنموذج خامس مجاني بالكامل، مع ميزات لا تجدها في أي نسخة أخرى.

---

## الفرق عن النسخة الأصلية

| الميزة | النسخة الأصلية (Claude) | نسخة Manus (هذه) |
|--------|------------------------|-----------------|
| عدد النماذج | 4 | **5 (+ Manus مجاناً)** |
| توليد الصور | DALL-E 3 (يحتاج OpenAI key) | **Manus Image API مجاني** |
| بحث الويب | ❌ | **✅ بحث حقيقي** |
| تنفيذ الكود | sandbox محدود | **Python حقيقي** |
| Vision | 3 نماذج | **4 نماذج** |
| النموذج الخامس | ❌ | **✅ Manus مجاناً** |

---

## النماذج المدعومة

| النموذج | الشركة | الدور | API Key |
|---------|--------|-------|---------|
| **Claude Sonnet** | Anthropic | المحلل الناقد | `ANTHROPIC_API_KEY` |
| **GPT-4o** | OpenAI | المبرمج العملي | `OPENAI_API_KEY` |
| **Gemini 2.5 Flash** | Google | الباحث المبتكر | `GEMINI_API_KEY` |
| **DeepSeek Chat** | DeepSeek | الرياضيات والكود | `DEEPSEEK_API_KEY` |
| **Manus** ✦ | Manus AI | الوكيل الذكي متعدد القدرات | **مجاني - لا يحتاج key** |

---

## الميزات الحصرية لوكيل Manus ✦

### 1. توليد الصور المجاني
```
POST /api/manus/generate-image
{"prompt": "شعار لمشروع تقني أنيق"}
```
يولّد صوراً عالية الجودة بدون أي تكلفة إضافية.

### 2. البحث على الويب
```
POST /api/manus/web-search
{"query": "أحدث أسعار استضافة المواقع 2025"}
```
يجلب معلومات حديثة من الإنترنت في الوقت الفعلي.

### 3. تنفيذ الكود الحقيقي
```
POST /api/manus/execute-code
{"code": "print('Hello from Manus!')", "language": "python"}
```
يُشغّل الكود فعلاً ويعطيك النتيجة الحقيقية.

### 4. تحليل الصور (Vision)
وكيل Manus يحلل الصور بجانب Claude وGPT وGemini — 4 منظورات بدلاً من 3.

---

## التثبيت والتشغيل

### المتطلبات
- Python 3.11+
- مفتاح API واحد على الأقل (Gemini مجاني من [aistudio.google.com](https://aistudio.google.com))

### خطوات التثبيت

```bash
# 1. استنساخ المشروع
git clone https://github.com/tsallabi/AGENTS-SCOLLAB-LIBYAPRO-AI.git
cd AGENTS-SCOLLAB-LIBYAPRO-AI/backend

# 2. إنشاء البيئة الافتراضية
python -m venv venv
source venv/bin/activate  # Linux/Mac
# أو: venv\Scripts\activate  # Windows

# 3. تثبيت المتطلبات
pip install -r requirements.txt

# 4. إعداد ملف البيئة
cp .env.example .env
# عدّل .env وأضف مفاتيح API
```

### ملف `.env`

```env
APP_NAME=Agents Collab + Manus
APP_ENV=development
PORT=8001
DATABASE_URL=sqlite+aiosqlite:///./agentforge_manus.db
SECRET_KEY=your-secret-key-here

# مفاتيح AI (أضف ما تملكه)
SERVER_ANTHROPIC_KEY=sk-ant-...
SERVER_OPENAI_KEY=sk-...
SERVER_GEMINI_KEY=AIza...
SERVER_DEEPSEEK_KEY=sk-...

# Manus (مجاني - لا يحتاج إعداد)
# BUILT_IN_FORGE_API_URL=  # يُضبط تلقائياً
# BUILT_IN_FORGE_API_KEY=  # يُضبط تلقائياً
```

### تشغيل السيرفر

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

افتح المتصفح على: `http://localhost:8001`

---

## هيكل المشروع

```
AGENTS-SCOLLAB-LIBYAPRO-AI/
├── backend/
│   ├── app/
│   │   ├── agent_manus.py          # ✦ وكيل Manus الحصري
│   │   ├── routes_manus_exclusive.py # ✦ API endpoints حصرية
│   │   ├── agents.py               # النماذج الأربعة الأصلية
│   │   ├── orchestrator.py         # منطق الإجماع والتناوب
│   │   ├── routes_chat.py          # WebSocket للمحادثة
│   │   ├── routes_images.py        # DALL-E 3
│   │   ├── routes_files.py         # رفع الملفات + PDF
│   │   └── ...
│   └── requirements.txt
└── frontend/
    └── index.html                  # واجهة React (single file)
```

---

## المقارنة مع النسخة الأصلية

**النسخة الأصلية:** [github.com/tsallabi/LibyaPro-AI](https://github.com/tsallabi/LibyaPro-AI)

**هذه النسخة:** تضيف وكيل Manus الخامس مع قدرات حصرية لا تجدها في أي نسخة أخرى.

---

## الترخيص

MIT License — مفتوح المصدر للاستخدام والتطوير.

---

*بُني بتعاون بين Claude AI وManus AI تحت إشراف Tarek Sallabi*
