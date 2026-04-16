# 🚀 Module Resource Estimation: Question_AI (Module 2)

## 1. Module Basic Info

* **Module Name:** Question_AI — Module 2 (AI Interview Brain)
* **Owner:** Prem / Project Questioner
* **Description (2–3 lines):** Orchestrates AI interview flows including face-verification gating, dynamic question generation, and lenient answer evaluation using Groq LLM and Azure Speech Services.
* **Criticality:** High

---

## 2. Functional Responsibilities

* [x] API Handling (FastAPI)
* [x] Database Operations (In-memory Session Store)
* [x] File Upload / Processing (Audio blobs for STT)
* [ ] Real-time Processing (Ngrok tunneling used, but no active WebSockets yet)
* [x] Background Jobs (Async tasks for LLM/TTS calls)
* [x] External API Calls (Groq, Azure Speech)
* [x] CPU-heavy computation (Response parsing, evaluation logic)
* [ ] GPU / ML model usage (Calls external LLM, so local GPU not required)

---

## 3. Workload Characteristics

### 👥 Expected Users

* **Concurrent Users:** 50 - 100
* **Requests per second (RPS):** 5 - 15 (Burst usage during interview cycles)
* **Peak Load Scenario:** High-volume recruitment drives or simultaneous exam windows.

### ⏱️ Execution Nature

* [ ] Short-lived (<1 sec)
* [x] Medium (1–5 sec) - Question generation usually falls here.
* [x] Long-running (>5 sec) - Complex evaluation or long audio transcriptions.

---

## 4. Processing Type (IMPORTANT)

### CPU Usage

* [ ] Low (CRUD APIs)
* [x] Medium (logic + validation + orchestration)
* [ ] High (compilation, heavy logic)

### Memory Usage

* [ ] Low (<500MB)
* [x] Medium (500MB – 2GB) - LangChain and Azure SDK overhead.
* [ ] High (>2GB)

### Disk Usage

* [x] Minimal (Temporary storage for audio chunks)
* [ ] Moderate (logs/files)
* [ ] Heavy (media/storage)

### Network Usage

* [ ] Low
* [ ] Medium
* [x] High (Streaming audio to Azure, multiple LLM round-trips)

---

## 5. External Dependencies

| Service         | Type      | Load Impact |
| --------------- | --------- | ----------- |
| Groq LLM        | AI/LLM    | Medium (Latency dependent) |
| Azure Speech    | TTS/STT   | High (Bandwidth / Latency) |
| Ngrok           | Tunneling | Low         |

---

## 6. Resource Requirement Estimation

### 🔹 Minimum (Testing / Small Scale)

* **vCPU:** 2
* **Clock Speed:** 2.0+ GHz
* **RAM:** 2GB
* **Disk:** 10GB
* **Notes:** Suitable for single-user dev testing.

---

### 🔹 Recommended (Production)

* **vCPU:** 4
* **Clock Speed:** 2.4+ GHz
* **RAM:** 4GB
* **Disk:** 20GB
* **Notes:** Handles 50+ concurrent sessions comfortably.

---

### 🔹 High Load (Peak / Events)

* **vCPU:** 8+
* **Clock Speed:** 3.0+ GHz
* **RAM:** 8GB
* **Disk:** 50GB
* **Notes:** Vertical scaling for burst stability; horizontal scaling preferred.

---

## 7. Scaling Strategy

* [ ] Vertical Scaling (increase CPU/RAM)
* [x] Horizontal Scaling (multiple instances behind a LB)
* [ ] Queue-based processing (Current system is synchronous-async)
* [x] Auto-scaling required (Based on vCPU/RAM usage)

---

## 8. Bottleneck Identification

* Main bottleneck: External API Latency (Groq/Azure) & Network Bandwidth for Audio.
* Secondary bottleneck: In-memory session store (limiting horizontal scale if not moved to Redis).
* Failure risk under load: Rate limiting from external providers or memory exhaustion during high concurrent uploads.

---

## 9. Special Requirements

* [ ] GPU required
* [x] Low latency (<500ms for orchestration, LLM can be slower)
* [x] High availability (99.9%+)
* [x] Real-time constraints (for conversational feel)
* [x] Data privacy / security critical (Handling PII and interview recordings)

---

## 10. Final Summary (1–2 lines)

👉 "The Questioner Backend is a network-intensive, medium-CPU module requiring 4 vCPU and 4GB RAM for production, with horizontal scaling recommended for session stability."
