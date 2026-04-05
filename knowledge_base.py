"""
Knowledge Base Manager for Call Center Agent.
Loads company-specific knowledge from JSON files and provides
function declarations for Gemini Live API tool use.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")


class KnowledgeBase:
    """Manages company-specific knowledge bases for the AI agent."""

    def __init__(self):
        self.companies = {}
        self._load_all()

    def _load_all(self):
        """Load all knowledge base JSON files from the knowledge directory."""
        if not os.path.exists(KNOWLEDGE_DIR):
            logger.warning(f"Knowledge directory not found: {KNOWLEDGE_DIR}")
            return

        for filename in os.listdir(KNOWLEDGE_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(KNOWLEDGE_DIR, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    company_id = filename.replace(".json", "")
                    self.companies[company_id] = data
                    logger.info(f"Loaded knowledge base: {company_id} ({data.get('company', 'Unknown')})")
                except Exception as e:
                    logger.error(f"Failed to load {filename}: {e}")

    def get_company_ids(self):
        """Return list of available company IDs."""
        return list(self.companies.keys())

    def get_company_info(self, company_id: str) -> dict:
        """Get full company data."""
        return self.companies.get(company_id, {})

    def get_company_name(self, company_id: str) -> str:
        """Get human-readable company name."""
        data = self.companies.get(company_id, {})
        return data.get("company", company_id)

    def search_knowledge(self, company_id: str, query: str) -> str:
        """
        Search the knowledge base for relevant information.
        Uses keyword matching for the MVP.
        Returns the most relevant answer(s).
        """
        data = self.companies.get(company_id)
        if not data:
            return "Keine Informationen zu diesem Unternehmen verfügbar."

        query_lower = query.lower()
        results = []
        best_score = 0

        categories = data.get("categories", {})
        for cat_id, category in categories.items():
            for entry in category.get("entries", []):
                question = entry.get("question", "").lower()
                answer = entry.get("answer", "")

                # Simple keyword scoring
                score = 0
                query_words = query_lower.split()
                for word in query_words:
                    if len(word) > 2 and word in question:
                        score += 2
                    if len(word) > 2 and word in answer.lower():
                        score += 1

                if score > 0:
                    results.append((score, category.get("title", ""), entry))
                    if score > best_score:
                        best_score = score

        if not results:
            return "Zu dieser Frage habe ich leider keine spezifischen Informationen in der Wissensdatenbank gefunden. Ich helfe Ihnen trotzdem gerne weiter."

        # Return top results
        results.sort(key=lambda x: x[0], reverse=True)
        top_results = results[:3]

        response_parts = []
        for score, category_title, entry in top_results:
            response_parts.append(
                f"[{category_title}] {entry['question']}: {entry['answer']}"
            )

        return "\n\n".join(response_parts)

    def check_escalation(self, company_id: str, text: str) -> dict:
        """
        Check if the customer's message contains escalation triggers.
        Returns escalation status and message.
        """
        data = self.companies.get(company_id, {})
        triggers = data.get("escalation_triggers", [])
        text_lower = text.lower()

        triggered = [t for t in triggers if t.lower() in text_lower]

        if triggered:
            return {
                "should_escalate": True,
                "triggers_found": triggered,
                "message": data.get("escalation_message", "Ich verbinde Sie mit einem Mitarbeiter.")
            }

        return {
            "should_escalate": False,
            "triggers_found": [],
            "message": ""
        }

    def get_system_prompt(self, company_id: str) -> str:
        """
        Generate the system prompt for the AI agent based on company data.
        """
        data = self.companies.get(company_id, {})
        company_name = data.get("company", "Unbekannt")
        greeting = data.get("greeting", "Willkommen, wie kann ich Ihnen helfen?")
        language = data.get("language", "de")

        # Build a summary of available knowledge categories
        categories = data.get("categories", {})
        category_list = ", ".join([
            cat.get("title", cat_id)
            for cat_id, cat in categories.items()
        ])

        return f"""Du bist ein professioneller Kundenservice-Mitarbeiter von {company_name}.

WICHTIGE REGELN:
1. Sprich IMMER auf Deutsch. Antworte NIEMALS auf Englisch.
2. Sei höflich, professionell und hilfsbereit.
3. Halte deine Antworten kurz und präzise — du bist am Telefon, nicht in einem Chat.
4. Begrüße den Kunden beim ersten Kontakt mit: "{greeting}"
5. Wenn du eine Frage nicht beantworten kannst, nutze die Funktion 'search_knowledge' um in der Wissensdatenbank nachzuschlagen.
6. Wenn der Kunde wütend wird oder eskalieren möchte, nutze die Funktion 'check_escalation' um zu prüfen ob eine Weiterleitung nötig ist.
7. Du darst KEINE Bestellungen aufgeben, Konten ändern oder Zahlungen verarbeiten. Du kannst nur Informationen geben.
8. Beende das Gespräch freundlich wenn der Kunde sich verabschiedet.

VERFÜGBARE WISSENSBEREICHE: {category_list}

SPRACHSTIL:
- Verwende "Sie" (formelle Anrede)
- Sprich natürlich und flüssig, wie ein echter Mensch am Telefon
- Vermeide Fachbegriffe wenn möglich
- Sage "Einen Moment bitte" wenn du nachschlagen musst
"""

    def get_tool_declarations(self):
        """
        Return function declarations for Gemini Live API tool use.
        """
        return [
            {
                "name": "search_knowledge",
                "description": "Durchsucht die Wissensdatenbank des Unternehmens nach relevanten Informationen zu einer Kundenfrage. Nutze diese Funktion wenn der Kunde eine spezifische Frage hat über Bestellungen, Lieferung, Retouren, Zahlung oder Produkte.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Die Suchanfrage oder Frage des Kunden auf Deutsch"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "check_escalation",
                "description": "Prüft ob ein Kundengespräch an einen menschlichen Mitarbeiter weitergeleitet werden muss. Nutze diese Funktion wenn der Kunde sehr unzufrieden ist, einen Vorgesetzten verlangt, oder rechtliche Schritte erwähnt.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_message": {
                            "type": "string",
                            "description": "Die letzte Nachricht oder Zusammenfassung der Beschwerde des Kunden"
                        }
                    },
                    "required": ["customer_message"]
                }
            }
        ]


# Singleton instance
kb = KnowledgeBase()
