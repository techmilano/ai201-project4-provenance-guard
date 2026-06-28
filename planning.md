# Provenance Guard Planning

## Project Overview

Provenance Guard is a Flask API backend that classifies submitted text content as likely AI-generated, likely human-written, or uncertain. The system is designed for a creative writing platform that wants to provide attribution transparency without unfairly punishing creators.

The system uses two detection signals: a Groq LLM classification signal and a stylometric heuristic signal. The result is converted into a confidence score, a reader-facing transparency label, and a structured audit-log entry. Creators can appeal classifications, and appealed content is marked as under review.

## Architecture

### Submission Flow

```text
Client
  |
  | POST /submit
  | { text, creator_id }
  v
Flask API
  |
  | validate request + generate content_id
  v
Detection Pipeline
  |
  |--> Signal 1: Groq LLM classification
  |       output: ai_probability score from 0.0 to 1.0
  |
  |--> Signal 2: Stylometric heuristics
          output: ai_probability score from 0.0 to 1.0
  |
  v
Confidence Scoring
  |
  | weighted combined score
  v
Transparency Label Generator
  |
  | label text + attribution category
  v
Audit Log
  |
  | structured decision entry
  v
JSON Response