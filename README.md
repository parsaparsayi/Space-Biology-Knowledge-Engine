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

