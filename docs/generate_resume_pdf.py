#!/usr/bin/env python3
"""Generate industry-standard resume PDF (Jake's Resume-inspired layout for tech/ML)."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parent / "Hansit_Varshney_Resume.pdf"

# Jake's-style: tight margins, high density, single column, right-aligned dates
MARGIN_L = 11
MARGIN_R = 11
MARGIN_T = 10
MARGIN_B = 10
LINE = 4.0
BULLET_INDENT = 8


class ResumePDF(FPDF):
  def __init__(self) -> None:
    super().__init__()
    self.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
    self.set_auto_page_break(auto=True, margin=MARGIN_B)

  @property
  def content_width(self) -> float:
    return self.epw

  def ensure_space(self, mm: float) -> None:
    if self.get_y() + mm > self.h - self.b_margin:
      self.add_page()

  def section(self, title: str) -> None:
    self.ensure_space(9)
    self.ln(1.5)
    self.set_font("Helvetica", "B", 10)
    self.set_x(self.l_margin)
    self.cell(self.content_width, 4.5, title.upper(), new_x="LMARGIN", new_y="NEXT")
    y = self.get_y()
    self.set_draw_color(0, 0, 0)
    self.set_line_width(0.3)
    self.line(self.l_margin, y, self.l_margin + self.content_width, y)
    self.ln(2)

  def body(self, text: str, *, style: str = "", size: float = 9) -> None:
    self.set_font("Helvetica", style, size)
    self.set_x(self.l_margin)
    self.multi_cell(self.content_width, LINE, text)

  def two_col_row(self, left: str, right: str, *, left_style: str = "B", right_style: str = "I", size: float = 9) -> None:
    """Bold left + italic right-aligned dates (Jake's Resume entry header)."""
    self.ensure_space(6)
    self.set_font("Helvetica", left_style, size)
    left_w = self.content_width * 0.72
    right_w = self.content_width * 0.28
    self.set_x(self.l_margin)
    self.cell(left_w, LINE, left, align="L")
    self.set_font("Helvetica", right_style, size)
    self.cell(right_w, LINE, right, align="R", new_x="LMARGIN", new_y="NEXT")

  def subtitle(self, text: str) -> None:
    self.set_font("Helvetica", "I", 9)
    self.set_x(self.l_margin)
    self.multi_cell(self.content_width, LINE, text)

  def tech_line(self, text: str) -> None:
    self.set_font("Helvetica", "I", 8.5)
    self.set_x(self.l_margin)
    self.multi_cell(self.content_width, 3.8, text)

  def bullet(self, text: str) -> None:
    self.set_font("Helvetica", "", 8.8)
    x = self.l_margin + BULLET_INDENT
    self.set_x(x)
    self.multi_cell(self.content_width - BULLET_INDENT, LINE, f"- {text}")

  def bullets(self, items: list[str]) -> None:
    for item in items:
      self.bullet(item)


def build_pdf() -> ResumePDF:
  pdf = ResumePDF()
  pdf.add_page()
  w = pdf.content_width

  # ---- Header (centered, Jake's style) ----
  pdf.set_font("Helvetica", "B", 20)
  pdf.cell(w, 8, "Hansit Varshney", align="C", new_x="LMARGIN", new_y="NEXT")
  pdf.set_font("Helvetica", "", 8.8)
  contact = (
    "Gurgaon, India  |  hansitvarshney@gmail.com  |  +91 9205256900  |  "
    "linkedin.com/in/hansit-varshney-4b8903186  |  github.com/hansitvarshney"
  )
  pdf.set_x(pdf.l_margin)
  pdf.multi_cell(w, 3.8, contact, align="C")
  pdf.ln(1)

  # ---- Education (first for new grad — Jake's convention) ----
  pdf.section("Education")
  pdf.two_col_row("Sushant University", "Gurgaon, India  |  May 2026")
  pdf.subtitle("B.Tech, Computer Science Engineering (AI & ML); Minor in Artificial Intelligence")
  pdf.body(
    "Relevant coursework: Deep Learning, NLP, Predictive Modeling, Data Structures & Algorithms",
    size=8.8,
  )
  pdf.ln(0.5)
  pdf.two_col_row("Scottish High International School", "Gurgaon, India")
  pdf.body("CBSE Class XII: 90% (2019)  |  Class X: 93% (2017)", size=8.8)

  # ---- Experience ----
  pdf.section("Experience")
  pdf.two_col_row("SKIC Pvt. Ltd.", "Gurgaon, India  |  Jan 2025 - Present")
  pdf.subtitle("Part-time Systems Developer & Operations Analyst")
  pdf.bullets(
    [
      "Deployed EPCDash in production across multiple EPC construction projects; reduced manual reporting by ~2-3 hours/day and decreased quantity, labour, and billing errors.",
      "Gathered requirements from project managers and site teams; translated Excel/WhatsApp field workflows into structured, automated reporting pipelines.",
    ]
  )
  pdf.ln(0.8)

  pdf.two_col_row("upGrad x Uber (MentorMind)", "Remote  |  Jun 2024 - Jul 2024")
  pdf.subtitle("Mentor-Led Data Science Program  |  Certified by upGrad Education Pvt. Ltd.")
  pdf.bullets(
    [
      "Built a capstone model to forecast hourly traffic volumes at road junctions using feature engineering, visualization, and predictive modeling on historical traffic data.",
    ]
  )
  pdf.ln(0.8)

  pdf.two_col_row("Cipla", "India  |  Jun 2021 - Aug 2021")
  pdf.subtitle("Business Intelligence Analyst")
  pdf.bullets(
    [
      "Produced SQL-driven KPI dashboards and recurring reports for pharmaceutical business stakeholders; validated data quality and documented reporting logic.",
    ]
  )

  # ---- Projects ----
  pdf.section("Projects")
  pdf.two_col_row("EPCDash - Enterprise EPC Project Command Center", "Jun 2026")
  pdf.tech_line("Python, FastAPI, Next.js, LangGraph, Google Gemini, SQLite, Railway")
  pdf.tech_line("github.com/hansitvarshney/EPCDash  |  Live demo on Railway")
  pdf.bullets(
    [
      "Built a full-stack EPC command center bridging on-site engineering schedules and client billing tranches with decoupled progress vs. payment-milestone data models.",
      "Orchestrated a LangGraph multi-agent pipeline for multimodal site-data ingestion (Gemini Flash), Pydantic validation, and dynamic Excel integration.",
      "Delivered cash-flow auditing dashboard with uninvoiced work-value tracking; deployed for live use at SKIC Pvt. Ltd.",
    ]
  )
  pdf.ln(0.8)

  pdf.two_col_row("LLMOps Gateway & Observability Platform", "Jul 2026")
  pdf.tech_line("Python, FastAPI, Redis, Qdrant, PostgreSQL, OpenTelemetry, Docker, arq")
  pdf.tech_line("github.com/hansitvarshney/llmops-gateway")
  pdf.bullets(
    [
      "Engineered an async multi-tenant LLM proxy with OpenAI/Anthropic adapters, dual-layer caching (Redis + Qdrant semantic), circuit breakers, and cross-provider failover routing.",
      "Shipped multi-tenant API-key auth, per-tenant rate limiting, Postgres trace persistence, and background workers; 127+ unit tests, Dockerized production stack.",
    ]
  )
  pdf.ln(0.8)

  pdf.two_col_row("AEVAR - GraphRAG Financial Audit Pipeline", "Jun 2026")
  pdf.tech_line("Python, Neo4j, Pydantic, Google Gemini, Streamlit")
  pdf.tech_line("github.com/hansitvarshney/AEVAR  |  Streamlit demo live")
  pdf.bullets(
    [
      "Built Pydantic-gated invoice ingestion with quarantine routing; implemented Neo4j GraphRAG for vendor/contract context on flagged transactions.",
      "Deployed schema-constrained Gemini agent producing typed executive risk briefings (fraud exposure, risk score, remediation actions).",
    ]
  )
  pdf.ln(0.8)

  pdf.two_col_row("Academic ML Portfolio", "Coursework")
  pdf.bullets(
    [
      "IMDB Sentiment (GRU): NLP classifier with custom tokenization and sequence modeling.",
      "Face CNN (LFW): 7-class image classifier  |  Credit Card Fraud: Isolation Forest on imbalanced data.",
      "Fashion MNIST: neural classifier achieving ~88% accuracy with training and prediction visualizations.",
    ]
  )

  # ---- Technical Skills (last — Jake's convention) ----
  pdf.section("Technical Skills")
  pdf.body("Languages: Python, SQL, TypeScript", size=8.8)
  pdf.body(
    "ML & AI: TensorFlow, Keras, Scikit-learn, Pandas, NumPy, LangGraph, RAG, GraphRAG, Gemini, OpenAI",
    size=8.8,
  )
  pdf.body(
    "Backend & Data: FastAPI, SQLAlchemy, Redis, PostgreSQL, Neo4j, Qdrant, Docker, OpenTelemetry, pytest",
    size=8.8,
  )
  pdf.body("Frontend: Next.js, React, Tailwind CSS, Streamlit", size=8.8)

  return pdf


def main() -> None:
  pdf = build_pdf()
  pdf.output(str(OUT))
  print(f"Wrote {OUT} ({pdf.page_no()} page(s))")


if __name__ == "__main__":
  main()
