"""
services/question_bank.py
=========================
Predefined question bank & skill-matching fallback engine.

When the LLM fails to generate valid questions after MAX_RETRIES,
this module takes the candidate's skills from the resume JSON,
matches them against the question bank, and returns exactly 15
diverse, non-repetitive questions — no external API calls.

Data structure:
    QUESTION_BANK is a dict keyed by normalised skill category.
    Each value is a list of question dicts with difficulty + category.
    This acts as an inverted index:  skill → [questions].

Retrieval:
    1. Normalise & deduplicate candidate skills
    2. Match against bank keys (exact + partial/alias)
    3. Round-robin across matched skills for diversity
    4. Pad from "General" if not enough questions
"""

import random
import re
from typing import List, Optional

from schemas import CandidateProfile, Question


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  QUESTION BANK                                                             ║
# ║  Keys = normalised skill names (lowercase)                                 ║
# ║  Values = list of { difficulty, category, question }                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

QUESTION_BANK: dict[str, list[dict]] = {

    # ── Python ──────────────────────────────────────────────────────────────────
    "python": [
        {"difficulty": "easy",   "category": "technical", "question": "What are the key differences between a list and a tuple in Python?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the difference between deep copy and shallow copy in Python."},
        {"difficulty": "easy",   "category": "technical", "question": "What are Python decorators and when would you use them?"},
        {"difficulty": "medium", "category": "technical", "question": "How does Python's Global Interpreter Lock (GIL) affect multithreading?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain context managers in Python and how you would write a custom one."},
        {"difficulty": "medium", "category": "technical", "question": "What is the difference between `__str__` and `__repr__` in Python?"},
        {"difficulty": "hard",   "category": "technical", "question": "How would you design a metaclass in Python and what problem does it solve?"},
        {"difficulty": "hard",   "category": "technical", "question": "Explain Python's memory management and garbage collection mechanism."},
    ],

    # ── JavaScript / TypeScript ─────────────────────────────────────────────────
    "javascript": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between `let`, `const`, and `var` in JavaScript?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain how closures work in JavaScript with an example."},
        {"difficulty": "easy",   "category": "technical", "question": "What is the event loop in JavaScript and why is it important?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain the difference between Promises, async/await, and callbacks."},
        {"difficulty": "medium", "category": "technical", "question": "What is prototypal inheritance in JavaScript and how does it differ from classical inheritance?"},
        {"difficulty": "hard",   "category": "technical", "question": "How would you implement a debounce and throttle function from scratch?"},
        {"difficulty": "hard",   "category": "technical", "question": "Explain how the V8 engine's JIT compilation optimises JavaScript execution."},
    ],

    # ── React ───────────────────────────────────────────────────────────────────
    "react": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the Virtual DOM and how does React use it for rendering?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the difference between functional and class components in React."},
        {"difficulty": "medium", "category": "technical", "question": "How do React hooks like useState and useEffect work internally?"},
        {"difficulty": "medium", "category": "technical", "question": "What is prop drilling and how can you avoid it in a React application?"},
        {"difficulty": "hard",   "category": "technical", "question": "How would you implement code-splitting and lazy loading in a large React application?"},
        {"difficulty": "hard",   "category": "technical", "question": "Explain React's reconciliation algorithm and its performance implications."},
    ],

    # ── Machine Learning / AI ───────────────────────────────────────────────────
    "machine learning": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between supervised and unsupervised learning?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain bias-variance trade-off in machine learning."},
        {"difficulty": "easy",   "category": "technical", "question": "What is overfitting and how can you prevent it?"},
        {"difficulty": "medium", "category": "technical", "question": "Compare and contrast gradient descent variants: batch, stochastic, and mini-batch."},
        {"difficulty": "medium", "category": "technical", "question": "How does a Random Forest differ from a single Decision Tree in performance and interpretability?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain precision, recall, and F1-score. When would you prioritise one over another?"},
        {"difficulty": "hard",   "category": "technical", "question": "How does backpropagation work in a neural network? Explain the chain rule's role."},
        {"difficulty": "hard",   "category": "technical", "question": "Describe the attention mechanism in transformers. Why is it better than RNNs for sequence tasks?"},
    ],

    # ── Data Science / Data Analysis ────────────────────────────────────────────
    "data science": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between correlation and causation?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the purpose of exploratory data analysis (EDA)."},
        {"difficulty": "medium", "category": "technical", "question": "How do you handle missing data in a dataset? Compare different imputation strategies."},
        {"difficulty": "medium", "category": "technical", "question": "What is feature engineering and why is it critical for model performance?"},
        {"difficulty": "hard",   "category": "technical", "question": "Explain dimensionality reduction techniques like PCA and t-SNE and when to use each."},
    ],

    # ── SQL / Databases ─────────────────────────────────────────────────────────
    "sql": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between INNER JOIN, LEFT JOIN, and FULL OUTER JOIN?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the difference between WHERE and HAVING clauses in SQL."},
        {"difficulty": "medium", "category": "technical", "question": "What are database indexes and how do they improve query performance?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain ACID properties in databases with real-world examples."},
        {"difficulty": "hard",   "category": "technical", "question": "How would you optimise a slow-running query on a table with millions of rows?"},
        {"difficulty": "hard",   "category": "technical", "question": "Explain the difference between normalisation and denormalisation. When would you denormalise?"},
    ],

    # ── Java ────────────────────────────────────────────────────────────────────
    "java": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between an abstract class and an interface in Java?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the concepts of encapsulation and polymorphism in Java."},
        {"difficulty": "medium", "category": "technical", "question": "How does garbage collection work in the JVM?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain the Java Collections framework. When would you use a HashMap vs a TreeMap?"},
        {"difficulty": "hard",   "category": "technical", "question": "What are the concurrency utilities in java.util.concurrent and how do they prevent race conditions?"},
    ],

    # ── C / C++ ─────────────────────────────────────────────────────────────────
    "c++": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between stack and heap memory allocation in C/C++?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain pointers and references in C++. When would you use each?"},
        {"difficulty": "medium", "category": "technical", "question": "What are smart pointers in C++? Compare unique_ptr, shared_ptr, and weak_ptr."},
        {"difficulty": "medium", "category": "technical", "question": "Explain the Rule of Three/Five in C++ and why it matters."},
        {"difficulty": "hard",   "category": "technical", "question": "How does virtual dispatch work in C++? Explain vtables and their overhead."},
    ],

    # ── Docker / DevOps ─────────────────────────────────────────────────────────
    "docker": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between a Docker image and a Docker container?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the purpose of a Dockerfile and its most common instructions."},
        {"difficulty": "medium", "category": "technical", "question": "How does Docker networking work? Compare bridge, host, and overlay networks."},
        {"difficulty": "medium", "category": "technical", "question": "What are multi-stage builds in Docker and how do they reduce image size?"},
        {"difficulty": "hard",   "category": "technical", "question": "How would you design a CI/CD pipeline using Docker containers for a microservices application?"},
    ],

    # ── Cloud / AWS ─────────────────────────────────────────────────────────────
    "aws": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between EC2 and Lambda in AWS?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the purpose of S3 and its storage classes."},
        {"difficulty": "medium", "category": "technical", "question": "How does an Application Load Balancer differ from a Network Load Balancer in AWS?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain VPC, subnets, and security groups in AWS networking."},
        {"difficulty": "hard",   "category": "technical", "question": "How would you architect a highly available, fault-tolerant application on AWS?"},
    ],

    # ── HTML / CSS ──────────────────────────────────────────────────────────────
    "html": [
        {"difficulty": "easy",   "category": "technical", "question": "What is semantic HTML and why is it important for accessibility?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the CSS box model and how padding, border, and margin interact."},
        {"difficulty": "medium", "category": "technical", "question": "What is the difference between Flexbox and CSS Grid? When would you choose one over the other?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain CSS specificity rules and how the cascade resolves conflicts."},
        {"difficulty": "hard",   "category": "technical", "question": "How would you design a fully responsive, accessible layout without any CSS framework?"},
    ],

    # ── Node.js ─────────────────────────────────────────────────────────────────
    "node.js": [
        {"difficulty": "easy",   "category": "technical", "question": "What is Node.js and how does its non-blocking I/O model work?"},
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between require and import in Node.js?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain the Node.js event loop phases and their execution order."},
        {"difficulty": "medium", "category": "technical", "question": "How do you handle errors effectively in an Express.js application?"},
        {"difficulty": "hard",   "category": "technical", "question": "How would you design a Node.js application to handle 10,000 concurrent WebSocket connections?"},
    ],

    # ── Git ──────────────────────────────────────────────────────────────────────
    "git": [
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between git merge and git rebase?"},
        {"difficulty": "easy",   "category": "technical", "question": "Explain the staging area in Git and how it fits into the commit workflow."},
        {"difficulty": "medium", "category": "technical", "question": "How would you resolve a merge conflict in Git? Walk through the process."},
        {"difficulty": "hard",   "category": "technical", "question": "Explain Git internals: blobs, trees, and commits. How does Git store data?"},
    ],

    # ── REST API / FastAPI / Flask ──────────────────────────────────────────────
    "rest api": [
        {"difficulty": "easy",   "category": "technical", "question": "What are the main HTTP methods and their intended uses in RESTful APIs?"},
        {"difficulty": "easy",   "category": "technical", "question": "What is the difference between authentication and authorisation in APIs?"},
        {"difficulty": "medium", "category": "technical", "question": "Explain RESTful API versioning strategies and their trade-offs."},
        {"difficulty": "medium", "category": "technical", "question": "How do you implement rate limiting in a web API and why is it important?"},
        {"difficulty": "hard",   "category": "technical", "question": "Compare REST, GraphQL, and gRPC. When would you choose each?"},
    ],

    # ── General (Fallback) ──────────────────────────────────────────────────────
    "general": [
        {"difficulty": "easy",   "category": "general",     "question": "Tell me about yourself and your career aspirations."},
        {"difficulty": "easy",   "category": "general",     "question": "What motivates you to pursue a career in technology?"},
        {"difficulty": "easy",   "category": "behavioural", "question": "Describe a time when you had to learn a new technology quickly. How did you approach it?"},
        {"difficulty": "easy",   "category": "behavioural", "question": "How do you stay updated with the latest trends in your field?"},
        {"difficulty": "easy",   "category": "general",     "question": "What is your preferred development environment and why?"},
        {"difficulty": "easy",   "category": "behavioural", "question": "Describe a challenging project you worked on. What was the outcome?"},
        {"difficulty": "medium", "category": "behavioural", "question": "Tell me about a time you had a disagreement with a teammate. How did you resolve it?"},
        {"difficulty": "medium", "category": "behavioural", "question": "How do you approach debugging a complex issue in production?"},
        {"difficulty": "medium", "category": "project",     "question": "Walk me through a project you are most proud of. What was your role?"},
        {"difficulty": "medium", "category": "project",     "question": "How do you prioritise tasks when working on multiple projects simultaneously?"},
        {"difficulty": "medium", "category": "general",     "question": "What is the difference between a process and a thread?"},
        {"difficulty": "medium", "category": "general",     "question": "Explain the concept of version control and why it's essential for team projects."},
        {"difficulty": "hard",   "category": "behavioural", "question": "Describe a situation where you had to make a critical technical decision under pressure."},
        {"difficulty": "hard",   "category": "general",     "question": "What is the CAP theorem and how does it apply to distributed systems?"},
        {"difficulty": "hard",   "category": "general",     "question": "How would you design a system to handle high traffic and ensure fault tolerance?"},
    ],
}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ALIAS MAP  —  maps common abbreviations / variants to bank keys           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

_ALIAS_MAP: dict[str, str] = {
    # Python ecosystem
    "py":            "python",
    "python3":       "python",
    "django":        "python",
    "flask":         "python",
    "fastapi":       "python",
    # JS / TS
    "js":            "javascript",
    "typescript":    "javascript",
    "ts":            "javascript",
    "es6":           "javascript",
    "es2015":        "javascript",
    "jquery":        "javascript",
    "vue":           "javascript",
    "vuejs":         "javascript",
    "vue.js":        "javascript",
    "angular":       "javascript",
    "angularjs":     "javascript",
    "next.js":       "javascript",
    "nextjs":        "javascript",
    # React
    "reactjs":       "react",
    "react.js":      "react",
    "react native":  "react",
    # ML / AI
    "ml":            "machine learning",
    "ai":            "machine learning",
    "deep learning": "machine learning",
    "dl":            "machine learning",
    "nlp":           "machine learning",
    "natural language processing": "machine learning",
    "computer vision": "machine learning",
    "cv":            "machine learning",
    "tensorflow":    "machine learning",
    "pytorch":       "machine learning",
    "keras":         "machine learning",
    "scikit-learn":  "machine learning",
    "sklearn":       "machine learning",
    # Data
    "data analysis": "data science",
    "pandas":        "data science",
    "numpy":         "data science",
    "matplotlib":    "data science",
    "data analytics": "data science",
    "power bi":      "data science",
    "tableau":       "data science",
    "excel":         "data science",
    # Database
    "mysql":         "sql",
    "postgresql":    "sql",
    "postgres":      "sql",
    "sqlite":        "sql",
    "mongodb":       "sql",
    "nosql":         "sql",
    "database":      "sql",
    "rdbms":         "sql",
    # Java
    "spring":        "java",
    "spring boot":   "java",
    "springboot":    "java",
    "jvm":           "java",
    "kotlin":        "java",
    # C / C++
    "c":             "c++",
    "c language":    "c++",
    "cpp":           "c++",
    "c programming": "c++",
    # Docker / DevOps
    "kubernetes":    "docker",
    "k8s":           "docker",
    "devops":        "docker",
    "ci/cd":         "docker",
    "jenkins":       "docker",
    "terraform":     "docker",
    "ansible":       "docker",
    "docker compose":"docker",
    # Cloud
    "cloud":         "aws",
    "azure":         "aws",
    "gcp":           "aws",
    "google cloud":  "aws",
    "cloud computing": "aws",
    # HTML / CSS
    "css":           "html",
    "html5":         "html",
    "css3":          "html",
    "tailwind":      "html",
    "bootstrap":     "html",
    "sass":          "html",
    "scss":          "html",
    # Node
    "node":          "node.js",
    "nodejs":        "node.js",
    "express":       "node.js",
    "expressjs":     "node.js",
    "express.js":    "node.js",
    # Git
    "github":        "git",
    "gitlab":        "git",
    "bitbucket":     "git",
    "version control": "git",
    # REST
    "api":           "rest api",
    "graphql":       "rest api",
    "grpc":          "rest api",
    "rest":          "rest api",
    "restful":       "rest api",
    "postman":       "rest api",
}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SKILL MATCHING + RETRIEVAL ENGINE                                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

TARGET_COUNT = 15   # must always return exactly this many


def _normalise_skills(raw_skills: str) -> list[str]:
    """
    Split the comma-separated skill string into lowercase, deduplicated tokens.
    Handles semicolons, pipes, slashes as delimiters too.
    """
    tokens = re.split(r"[,;|/\n]+", raw_skills.lower())
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        t = t.strip().strip("-•● ")
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _resolve_skill(skill: str) -> Optional[str]:
    """
    Map a raw skill token to a question-bank key.
    Priority: exact match → alias → partial/substring match.
    """
    skill_lower = skill.lower().strip()

    # 1. Exact match against bank keys
    if skill_lower in QUESTION_BANK:
        return skill_lower

    # 2. Alias lookup
    if skill_lower in _ALIAS_MAP:
        return _ALIAS_MAP[skill_lower]

    # 3. Partial match: skill token appears inside a bank key or vice-versa
    for bank_key in QUESTION_BANK:
        if bank_key == "general":
            continue   # don't accidentally match everything to general
        if skill_lower in bank_key or bank_key in skill_lower:
            return bank_key

    # 4. Partial alias match
    for alias, target in _ALIAS_MAP.items():
        if skill_lower in alias or alias in skill_lower:
            return target

    return None


def _rank_matched_skills(matched: dict[str, int]) -> list[str]:
    """
    Sort matched skill categories by frequency (descending).
    Skills that appear more often in the resume are prioritised.
    """
    return sorted(matched.keys(), key=lambda k: matched[k], reverse=True)


def get_fallback_questions(profile: CandidateProfile) -> list[Question]:
    """
    Main entry point for the fallback system.
    Returns exactly 15 Question objects sourced from the predefined bank.

    Steps:
      1. Extract & normalise skills from the profile
      2. Match each skill to a bank category (exact → alias → partial)
      3. Count frequency of each matched category for ranking
      4. Round-robin pick questions across matched categories (diversity)
      5. Pad remaining slots from "General"
      6. Assign sequential IDs 1-15
    """
    raw = profile.skills or ""
    normalised = _normalise_skills(raw)

    # ── Match skills → bank categories with frequency count ───────────────────
    matched_freq: dict[str, int] = {}
    for skill in normalised:
        resolved = _resolve_skill(skill)
        if resolved and resolved != "general":
            matched_freq[resolved] = matched_freq.get(resolved, 0) + 1

    ranked_categories = _rank_matched_skills(matched_freq)

    # ── Collect candidate question pools ──────────────────────────────────────
    pools: dict[str, list[dict]] = {}
    for cat in ranked_categories:
        pool = list(QUESTION_BANK.get(cat, []))
        random.shuffle(pool)          # light shuffle to avoid determinism
        pools[cat] = pool

    # ── Round-robin pick for diversity ────────────────────────────────────────
    selected: list[dict] = []
    seen_questions: set[str] = set()

    # Keep cycling through ranked categories until we have enough or exhaust pools
    while len(selected) < TARGET_COUNT and pools:
        empty_cats = []
        for cat in ranked_categories:
            if cat not in pools:
                continue
            if len(selected) >= TARGET_COUNT:
                break
            pool = pools[cat]
            picked = False
            while pool and not picked:
                q = pool.pop(0)
                if q["question"] not in seen_questions:
                    selected.append(q)
                    seen_questions.add(q["question"])
                    picked = True
            if not pool:
                empty_cats.append(cat)
        # Remove exhausted categories
        for cat in empty_cats:
            del pools[cat]
            ranked_categories = [c for c in ranked_categories if c != cat]
        if not ranked_categories:
            break

    # ── Pad from General if still short ──────────────────────────────────────
    if len(selected) < TARGET_COUNT:
        general_pool = list(QUESTION_BANK.get("general", []))
        random.shuffle(general_pool)
        for q in general_pool:
            if len(selected) >= TARGET_COUNT:
                break
            if q["question"] not in seen_questions:
                selected.append(q)
                seen_questions.add(q["question"])

    # ── Assign IDs 1-15 ─────────────────────────────────────────────────────
    questions: list[Question] = []
    for idx, q_data in enumerate(selected[:TARGET_COUNT], start=1):
        questions.append(
            Question(
                id         = idx,
                difficulty = q_data.get("difficulty", "medium"),
                category   = q_data.get("category", "general"),
                question   = q_data["question"],
            )
        )

    return questions
