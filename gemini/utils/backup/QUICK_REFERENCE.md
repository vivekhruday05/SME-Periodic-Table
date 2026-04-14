# Gemini API - Quick Reference Card

## 🚀 30-Second Setup

```bash
# 1. Install
pip install google-generativeai

# 2. Get key
# Go to: https://aistudio.google.com/app/apikeys

# 3. Set environment
export GEMINI_API_KEY="your-key"
export GEMINI_MODEL="gemini-1.5-flash"

# 4. Test
python -c "from gemini.multitools import _get_gemini_model; print('✓' if _get_gemini_model() else '✗')"
```

## 📖 Essential Commands

### Generate Quiz
```python
from gemini.multitools import quiz_generator
import json

result = quiz_generator.invoke({
    "context": "Your content here...",
    "constraints": "Grade 8, 5 questions"
})

quiz = json.loads(result)["result"]
```

### Generate Report
```python
from gemini.multitools import report_generator
import json

result = report_generator.invoke({
    "context": "Your content here...",
    "topic": "Report Topic"
})

report = json.loads(result)["result"]
```

### With Orchestration Agent
```python
from agent import OrchestrationAgent

agent = OrchestrationAgent()
result = agent.process_request(
    "Quiz about X for Y grade and email to user@example.com"
)
```

## 🔑 Key Configuration

```bash
# Required
GEMINI_API_KEY=sk_...

# Optional (defaults)
GEMINI_MODEL=gemini-1.5-flash
```

## 📊 Model Comparison

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| flash-1.5 | ⚡⚡⚡ | ⭐⭐⭐ | $ |
| pro-1.5 | ⚡⚡ | ⭐⭐⭐⭐ | $$$ |
| flash-2.0 | ⚡⚡⚡ | ⭐⭐⭐⭐ | $$ |

## 💰 Pricing Quick Math

```
Gemini Flash (cheapest):
- 1 Quiz (~2k tokens): $0.0004
- 100/day: $0.04/day = $1.20/month
- 1000/month: $0.40/month = $4.80/year

Gemini Pro (best quality):
- 1 Quiz (~2k tokens): $0.013
- 100/day: $1.30/day = $39/month
```

## 🆘 Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| "Key not set" | `export GEMINI_API_KEY="..."` |
| "Invalid key" | Regenerate at https://aistudio.google.com/app/apikeys |
| "Rate limited" | Free tier = 50 req/min, wait or upgrade |
| "Slow response" | Use gemini-1.5-flash instead |
| "Model not found" | Use valid: flash, pro, or 2.0 variant |

## 📝 Error Handling Template

```python
import json
from gemini.multitools import quiz_generator

try:
    result = quiz_generator.invoke({
        "context": content,
        "constraints": constraints
    })
    
    data = json.loads(result)
    
    if data["status"] == "success":
        print(data["result"])
    else:
        print(f"Error: {data.get('message')}")
        
except Exception as e:
    print(f"Exception: {e}")
    # Check logs/tools.log for details
```

## 🧪 Quick Test

```bash
# Verify installation
python -c "import google.generativeai as genai; print('✓ Installed')"

# Check environment
python -c "import os; print('✓ Key set' if os.getenv('GEMINI_API_KEY') else '✗ Key missing')"

# Test API access
python << 'EOF'
import google.generativeai as genai
import os
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')
resp = model.generate_content('Hello!')
print('✓ API working' if resp.text else '✗ No response')
EOF
```

## 📚 Documentation Map

| File | What For |
|------|----------|
| README_GEMINI.md | Start here! |
| GEMINI_SETUP.md | Detailed setup |
| GEMINI_MIGRATION.md | What changed |
| GEMINI_CONVERSION_SUMMARY.md | Overview |
| ARCHITECTURE.md | System design |
| requirements_gemini.txt | Dependencies |

## 🔗 Useful Links

- API Keys: https://aistudio.google.com/app/apikeys
- Docs: https://ai.google.dev/docs
- Pricing: https://ai.google.dev/pricing
- Status: https://status.ai.google.com

## ⚡ Performance Benchmarks

```
Setup Time: <1 second (vs 30-60s with local)
Quiz Gen: 2-5 seconds (vs 8-15s with local)
Storage: <1 MB (vs 10 GB with local)
GPU Needed: No (vs Yes with local)
```

## 🎯 Common Workflows

### Workflow 1: Quiz Generation
```
User Input → Parse → Retrieve Context → Generate Quiz → Return JSON
                        ↓ genai API
```

### Workflow 2: Report Generation  
```
User Input → Parse → Retrieve Context → Generate Report → PDF → Email
                        ↓ genai API
```

### Workflow 3: Full Chain
```
Request → Agent → Retrieve → Generate → PDF → Email → User
          ↓ orchestrator    ↓ genai API
```

## ✅ Before Using in Production

- [ ] Set GEMINI_API_KEY
- [ ] Run tests: `python agent_examples.py`
- [ ] Check logs: `logs/tools.log`
- [ ] Monitor costs (if on paid tier)
- [ ] Set up error alerts
- [ ] Document in deployment guide

## 🚀 Ready to Go!

```python
from agent import OrchestrationAgent

agent = OrchestrationAgent()
result = agent.process_request(
    "Create chemistry quiz for 8th grade about periodic table"
)

print(result)  # Your quiz is ready!
```

## 📞 Quick Support

**Problem?** Check logs first:
```bash
tail -f logs/tools.log
```

**Still stuck?** Read relevant doc:
1. Setup → GEMINI_SETUP.md
2. Changes → GEMINI_MIGRATION.md  
3. Architecture → ARCHITECTURE.md

---

**That's it! You're ready to go! 🎉**

For detailed info, see README_GEMINI.md
