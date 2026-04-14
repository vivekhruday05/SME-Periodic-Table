from bs4 import BeautifulSoup
import re
import json

html = open("edurev_classification.html", encoding="utf-8").read()
soup = BeautifulSoup(html, "html.parser")

questions = []

# The main content lives inside this tag
container = soup.find("div", {"itemprop": "articleSection"})
all_ps = container.find_all("p")

Q_START = re.compile(r"^Q\.\s*\d+", re.IGNORECASE)

for p in all_ps:
    raw = p.get_text(" ", strip=True)

    # Identify Q.x
    if not Q_START.match(raw):
        continue

    # -------------------------
    # Extract exam year (2020)
    # -------------------------
    exam_match = re.search(r"\((\d{4})\)", raw)
    exam = exam_match.group(1) if exam_match else None

    # Remove the (2020) from text
    if exam:
        raw = re.sub(r"\(\d{4}\)", "", raw)

    # Clean double spaces
    question_text = re.sub(r"\s{2,}", " ", raw).strip()

    # Find blockquote after this <p>
    block = p.find_next("blockquote")
    correct_answer = None
    solution = None

    if block:
        btxt = block.get_text("\n", strip=True)

        # Extract answer after "Ans."
        ans_match = re.search(r"Ans\.\s*([a-dA-D])", btxt)
        if ans_match:
            correct_answer = ans_match.group(1)

        # The rest (after 'Ans.') is solution
        if "Ans." in btxt:
            solution = btxt.split("Ans.")[-1].strip()
            # Remove first line containing the option letter
            solution = re.sub(r"^[a-dA-D]\s*", "", solution).strip()

    questions.append({
        "question": question_text,
        "correct_answer": correct_answer,
        "solution": solution,
        "exam": exam
    })

# Save output
with open("d_and_f_block.json", "w", encoding="utf-8") as f:
    json.dump(questions, f, indent=2, ensure_ascii=False)

print("Extracted", len(questions), "questions!")
