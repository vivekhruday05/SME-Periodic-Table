from bs4 import BeautifulSoup
import re
import json

html = open("edurev_classification.html", encoding="utf-8").read()
soup = BeautifulSoup(html, "html.parser")

questions = []

container = soup.find("div", {"itemprop": "articleSection"})
all_ps = container.find_all("p")

Q_START = re.compile(r"^Q\.\s*\d+", re.IGNORECASE)

for p in all_ps:
    raw = p.get_text(" ", strip=True)

    if not Q_START.match(raw):
        continue

    # ------------------------------------------
    # Extract exam year
    # ------------------------------------------
    exam_match = re.search(r"\(JEE Main\s+\d{4}\)", raw)
    exam = exam_match.group(0).strip("()") if exam_match else None

    # ------------------------------------------
    # Remove ALL occurrences of (JEE Main YYYY)
    # from question text
    # ------------------------------------------
    if exam:
        raw = re.sub(r"\(JEE Main\s+\d{4}\)", "", raw)

    # Clean extra spaces
    question_text = re.sub(r"\s{2,}", " ", raw).strip()

    # ------------------------------------------
    # Answer + solution (blockquote)
    # ------------------------------------------
    block = p.find_next("blockquote")
    correct_answer = None
    solution = None

    if block:
        btext = block.get_text("\n", strip=True)
        
        ans_match = re.search(r"Correct Answer.*", btext)
        if ans_match:
            correct_answer = ans_match.group(0)

        if "Solution:" in btext:
            solution = btext.split("Solution:")[-1].strip()

    questions.append({
        "question": question_text,
        "correct_answer": correct_answer,
        "solution": solution,
        "exam": exam
    })

with open("periodic_properties.json", "w", encoding="utf-8") as f:
    json.dump(questions, f, indent=2, ensure_ascii=False)

print("Extracted", len(questions), "questions!")
