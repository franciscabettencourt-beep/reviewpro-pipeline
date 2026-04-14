# config/settings.py
# Mapeamento VTRL → Master
# Chave = coluna no output final (master)
# Valor = lista de possíveis nomes na origem (matching case-insensitive, strip)

COLUMN_MAPPING = {
    "RESORT":               ["property", "resort", "hotel", "property name"],
    "FIRST":                ["first name", "firstname", "first", "nome", "name first"],
    "LAST":                 ["last name", "lastname", "last", "apelido", "surname", "name last"],
    "PHONE_TYPE":           ["email", "e-mail", "email address", "guest email"],
    "PHONE_NUMBER":         ["checked out", "check out", "checkout", "status", "estado"],
    "ARRIVAL_DATE_TIME":    ["arrival date", "arrival", "check in date", "checkin date", "data chegada"],
    "DEPARTURE_DATE_TIME":  ["departure date", "departure", "check out date", "checkout date", "data saida", "data saída"],
    "LANGUAGE":             ["country code", "country", "nationality", "pais", "país"],
    "ROOM":                 ["room no", "room no.", "room", "quarto", "room number", "roomno"],
}

# Colunas que precisam de existir no output final (ordenadas)
OUTPUT_COLUMNS = [
    "RESORT",
    "FIRST",
    "LAST",
    "PHONE_TYPE",
    "PHONE_NUMBER",
    "ARRIVAL_DATE_TIME",
    "DEPARTURE_DATE_TIME",
    "LANGUAGE",
    "ROOM",
]

# Regra de língua
PORTUGUESE_COUNTRY_CODES = ["PT", "PRT", "PORTUGAL"]

# Valores aceites como CHECKED OUT no VTRL
CHECKEDOUT_VALUES = [
    "checked out", "checkout", "co", "check-out", "departed", "departed"
]

# Palavras-chave no GIR que causam EXCLUSÃO automática
EXCLUSION_KEYWORDS = [
    "reclamação", "reclamacao", "complaint", "complained",
    "incidente", "incident",
    "não enviar", "nao enviar", "do not send", "dns",
    "experiência negativa", "experiencia negativa", "bad experience",
    "service recovery", "sr pendente", "sr open",
    "opt-out", "optout", "unsubscribe",
    "não elegível", "nao elegivel", "not eligible",
    "problema grave", "serious issue",
]

# Palavras-chave no GIR que causam SUSPENSÃO (revisão humana)
SUSPENSION_KEYWORDS = [
    "follow-up", "followup", "follow up",
    "pendente", "pending",
    "em análise", "em analise", "under review",
    "aguardar", "wait",
    "situação sensível", "situacao sensivel", "sensitive",
    "sem resolução", "sem resolucao", "unresolved",
    "contactar", "contact first",
]

# Campos mínimos obrigatórios para o registo ser elegível
REQUIRED_FIELDS = ["FIRST", "LAST", "DEPARTURE_DATE_TIME"]

# Threshold para matching fuzzy (0-100)
FUZZY_EXACT_THRESHOLD = 95
FUZZY_PROBABLE_THRESHOLD = 75
