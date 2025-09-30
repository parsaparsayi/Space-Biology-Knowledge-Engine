# Space Biology Knowledge Engine

This project was developed for the NASA Space Apps Challenge 2025.  
It is a web application that helps users search, read, and summarize space-biology research using PubMed literature, while also pointing to NASA’s Open Science Data Repository (OSDR) for primary datasets.

---

## Features

- **PubMed Search** with advanced filters:
  - Year range
  - Text availability (abstract, full text, free full text)
  - Article attribute (systematic review, clinical trial, etc.)
  - Article type (journal article, letter, editorial, etc.)
  - Language
  - Species, sex, age, and “other” tags (preprint, retracted)

- **View Abstracts** directly in the app.

- **Summarize Abstracts**  
  AI summarizer if Transformers is installed, otherwise a simple fallback (first few sentences).

- **Translate Abstracts** into multiple languages.

- **Reputation Score (demo)**  
  Shows a bar and badge (High, Medium, Low).  
  *Note: these values are fixed and illustrative — not based on real PubMed or NASA metrics.*

- **NASA Data & Resources Page**  
  Dedicated page with curated links to GeneLab, ALSDA, OSDR APIs, and tutorials.

---

## Project Structure

- `server.py` – FastAPI backend with endpoints for search, abstracts, summarization, translation, and reputation scoring  
- `static/` – frontend files (`index.html`, `app.js`, `styles.css`)  
- `resources.html` – NASA resources page  
- `requirements.txt` – Python dependencies  
- `README.md` – project description and instructions  
- `LICENSE` – MIT License

---

## Quickstart

Follow these steps to run the app locally:

1. **Clone or download this repository**

   ```bash
   git clone https://github.com/<your-username>/space-biology-knowledge-engine.git
   cd space-biology-knowledge-engine
   Or click "Code → Download ZIP" on GitHub and unzip it.

(Optional, but recommended) Create a virtual environment
python -m venv .venv
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

2. Install dependencies
   pip install -r requirements.txt

3. Run the server
   uvicorn server:app --reload --host 127.0.0.1 --port 8010

4. Open the app
   Open your browser and go to:
   http://127.0.0.1:8010
