"""
translations.py
A real (not decorative) translation layer for Ledger's primary navigation
and dashboard chrome. The Language setting in Settings previously saved a
value that nothing ever read - this wires it up for real.

Scope, stated plainly: this covers the sidebar navigation, topbar, and the
main dashboard's labels/buttons - the parts of the app visible on every
page. It does NOT yet translate every string on every individual page
(forms, table headers, flash messages throughout the whole app). That
would be a much larger pass; this is an honest, working subset rather
than a fully localized app pretending to be more complete than it is.
"""

LANGUAGE_CODES = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Hindi": "hi",
    "Tamil": "ta",
}

TRANSLATIONS = {
    "en": {
        "nav_overview": "Overview", "nav_dashboard": "Dashboard", "nav_analytics_reports": "Analytics & Reports",
        "nav_money": "Money", "nav_expenses": "Expenses", "nav_income": "Income", "nav_budget": "Budget",
        "nav_goals": "Goals", "nav_accounts": "Accounts & Transfers", "nav_net_worth": "Net Worth",
        "nav_statements": "Statements", "nav_analytics": "Analytics", "nav_copilot": "Copilot",
        "nav_import": "Import", "nav_calendar": "Calendar", "nav_snapshot": "Snapshot",
        "nav_month_end_close": "Month-End Close", "nav_subscriptions": "Subscriptions",
        "nav_data": "Data", "nav_data_quality": "Data Quality", "nav_audit_log": "Audit Log",
        "nav_account_group": "Account", "nav_profile": "Profile", "nav_settings": "Settings",
        "search_placeholder": "Search transactions",
        "btn_add_expense": "Add Expense", "btn_add_income": "Add Income", "btn_save": "Save",
        "btn_cancel": "Cancel", "btn_edit": "Edit", "btn_delete": "Delete", "btn_logout": "Log out",
        "dash_welcome": "Welcome back", "dash_net_worth": "Net Worth", "dash_cash_flow": "Cash Flow (this month)",
        "dash_savings_rate": "Savings Rate", "dash_quick_links": "Quick Links",
        "dash_recent_transactions": "Recent Transactions", "dash_recent_activity": "Recent activity",
        "dash_view_all": "View all",
    },
    "es": {
        "nav_overview": "Resumen", "nav_dashboard": "Panel", "nav_analytics_reports": "Análisis e Informes",
        "nav_money": "Dinero", "nav_expenses": "Gastos", "nav_income": "Ingresos", "nav_budget": "Presupuesto",
        "nav_goals": "Metas", "nav_accounts": "Cuentas y Transferencias", "nav_net_worth": "Patrimonio Neto",
        "nav_statements": "Estados Financieros", "nav_analytics": "Análisis", "nav_copilot": "Copiloto",
        "nav_import": "Importar", "nav_calendar": "Calendario", "nav_snapshot": "Instantánea",
        "nav_month_end_close": "Cierre de Mes", "nav_subscriptions": "Suscripciones",
        "nav_data": "Datos", "nav_data_quality": "Calidad de Datos", "nav_audit_log": "Registro de Auditoría",
        "nav_account_group": "Cuenta", "nav_profile": "Perfil", "nav_settings": "Configuración",
        "search_placeholder": "Buscar transacciones",
        "btn_add_expense": "Añadir Gasto", "btn_add_income": "Añadir Ingreso", "btn_save": "Guardar",
        "btn_cancel": "Cancelar", "btn_edit": "Editar", "btn_delete": "Eliminar", "btn_logout": "Cerrar sesión",
        "dash_welcome": "Bienvenido de nuevo", "dash_net_worth": "Patrimonio Neto",
        "dash_cash_flow": "Flujo de Caja (este mes)", "dash_savings_rate": "Tasa de Ahorro",
        "dash_quick_links": "Accesos Rápidos", "dash_recent_transactions": "Transacciones Recientes",
        "dash_recent_activity": "Actividad reciente", "dash_view_all": "Ver todo",
    },
    "fr": {
        "nav_overview": "Aperçu", "nav_dashboard": "Tableau de bord", "nav_analytics_reports": "Analyses et Rapports",
        "nav_money": "Argent", "nav_expenses": "Dépenses", "nav_income": "Revenus", "nav_budget": "Budget",
        "nav_goals": "Objectifs", "nav_accounts": "Comptes et Virements", "nav_net_worth": "Valeur Nette",
        "nav_statements": "États Financiers", "nav_analytics": "Analytique", "nav_copilot": "Copilote",
        "nav_import": "Importer", "nav_calendar": "Calendrier", "nav_snapshot": "Instantané",
        "nav_month_end_close": "Clôture Mensuelle", "nav_subscriptions": "Abonnements",
        "nav_data": "Données", "nav_data_quality": "Qualité des Données", "nav_audit_log": "Journal d'Audit",
        "nav_account_group": "Compte", "nav_profile": "Profil", "nav_settings": "Paramètres",
        "search_placeholder": "Rechercher des transactions",
        "btn_add_expense": "Ajouter une Dépense", "btn_add_income": "Ajouter un Revenu", "btn_save": "Enregistrer",
        "btn_cancel": "Annuler", "btn_edit": "Modifier", "btn_delete": "Supprimer", "btn_logout": "Déconnexion",
        "dash_welcome": "Content de vous revoir", "dash_net_worth": "Valeur Nette",
        "dash_cash_flow": "Flux de Trésorerie (ce mois)", "dash_savings_rate": "Taux d'Épargne",
        "dash_quick_links": "Liens Rapides", "dash_recent_transactions": "Transactions Récentes",
        "dash_recent_activity": "Activité récente", "dash_view_all": "Tout voir",
    },
    "de": {
        "nav_overview": "Übersicht", "nav_dashboard": "Dashboard", "nav_analytics_reports": "Analysen & Berichte",
        "nav_money": "Geld", "nav_expenses": "Ausgaben", "nav_income": "Einnahmen", "nav_budget": "Budget",
        "nav_goals": "Ziele", "nav_accounts": "Konten & Überweisungen", "nav_net_worth": "Nettovermögen",
        "nav_statements": "Abschlüsse", "nav_analytics": "Analytik", "nav_copilot": "Copilot",
        "nav_import": "Importieren", "nav_calendar": "Kalender", "nav_snapshot": "Momentaufnahme",
        "nav_month_end_close": "Monatsabschluss", "nav_subscriptions": "Abonnements",
        "nav_data": "Daten", "nav_data_quality": "Datenqualität", "nav_audit_log": "Prüfprotokoll",
        "nav_account_group": "Konto", "nav_profile": "Profil", "nav_settings": "Einstellungen",
        "search_placeholder": "Transaktionen suchen",
        "btn_add_expense": "Ausgabe hinzufügen", "btn_add_income": "Einnahme hinzufügen", "btn_save": "Speichern",
        "btn_cancel": "Abbrechen", "btn_edit": "Bearbeiten", "btn_delete": "Löschen", "btn_logout": "Abmelden",
        "dash_welcome": "Willkommen zurück", "dash_net_worth": "Nettovermögen",
        "dash_cash_flow": "Cashflow (diesen Monat)", "dash_savings_rate": "Sparquote",
        "dash_quick_links": "Schnellzugriff", "dash_recent_transactions": "Letzte Transaktionen",
        "dash_recent_activity": "Letzte Aktivität", "dash_view_all": "Alle anzeigen",
    },
    "hi": {
        "nav_overview": "अवलोकन", "nav_dashboard": "डैशबोर्ड", "nav_analytics_reports": "विश्लेषण और रिपोर्ट",
        "nav_money": "पैसा", "nav_expenses": "खर्च", "nav_income": "आय", "nav_budget": "बजट",
        "nav_goals": "लक्ष्य", "nav_accounts": "खाते और स्थानांतरण", "nav_net_worth": "कुल संपत्ति",
        "nav_statements": "विवरण", "nav_analytics": "विश्लेषण", "nav_copilot": "कोपायलट",
        "nav_import": "आयात करें", "nav_calendar": "कैलेंडर", "nav_snapshot": "स्नैपशॉट",
        "nav_month_end_close": "माह-अंत समापन", "nav_subscriptions": "सदस्यताएँ",
        "nav_data": "डेटा", "nav_data_quality": "डेटा गुणवत्ता", "nav_audit_log": "ऑडिट लॉग",
        "nav_account_group": "खाता", "nav_profile": "प्रोफ़ाइल", "nav_settings": "सेटिंग्स",
        "search_placeholder": "लेन-देन खोजें",
        "btn_add_expense": "खर्च जोड़ें", "btn_add_income": "आय जोड़ें", "btn_save": "सहेजें",
        "btn_cancel": "रद्द करें", "btn_edit": "संपादित करें", "btn_delete": "हटाएं", "btn_logout": "लॉग आउट",
        "dash_welcome": "वापसी पर स्वागत है", "dash_net_worth": "कुल संपत्ति",
        "dash_cash_flow": "नकदी प्रवाह (इस महीने)", "dash_savings_rate": "बचत दर",
        "dash_quick_links": "त्वरित लिंक", "dash_recent_transactions": "हाल के लेन-देन",
        "dash_recent_activity": "हाल की गतिविधि", "dash_view_all": "सभी देखें",
    },
    "ta": {
        "nav_overview": "மேலோட்டம்", "nav_dashboard": "டாஷ்போர்டு", "nav_analytics_reports": "பகுப்பாய்வு & அறிக்கைகள்",
        "nav_money": "பணம்", "nav_expenses": "செலவுகள்", "nav_income": "வருமானம்", "nav_budget": "பட்ஜெட்",
        "nav_goals": "இலக்குகள்", "nav_accounts": "கணக்குகள் & பரிமாற்றங்கள்", "nav_net_worth": "நிகர மதிப்பு",
        "nav_statements": "அறிக்கைகள்", "nav_analytics": "பகுப்பாய்வு", "nav_copilot": "கோபைலட்",
        "nav_import": "இறக்குமதி", "nav_calendar": "நாட்காட்டி", "nav_snapshot": "ஸ்னாப்ஷாட்",
        "nav_month_end_close": "மாத இறுதி மூடல்", "nav_subscriptions": "சந்தாக்கள்",
        "nav_data": "தரவு", "nav_data_quality": "தரவு தரம்", "nav_audit_log": "தணிக்கை பதிவு",
        "nav_account_group": "கணக்கு", "nav_profile": "சுயவிவரம்", "nav_settings": "அமைப்புகள்",
        "search_placeholder": "பரிவர்த்தனைகளை தேடுங்கள்",
        "btn_add_expense": "செலவு சேர்க்க", "btn_add_income": "வருமானம் சேர்க்க", "btn_save": "சேமி",
        "btn_cancel": "ரத்துசெய்", "btn_edit": "திருத்து", "btn_delete": "நீக்கு", "btn_logout": "வெளியேறு",
        "dash_welcome": "மீண்டும் வருக", "dash_net_worth": "நிகர மதிப்பு",
        "dash_cash_flow": "பணப்புழக்கம் (இந்த மாதம்)", "dash_savings_rate": "சேமிப்பு விகிதம்",
        "dash_quick_links": "விரைவு இணைப்புகள்", "dash_recent_transactions": "சமீபத்திய பரிவர்த்தனைகள்",
        "dash_recent_activity": "சமீபத்திய செயல்பாடு", "dash_view_all": "அனைத்தையும் காண்க",
    },
}


def translate(key, language_name):
    code = LANGUAGE_CODES.get(language_name, "en")
    table = TRANSLATIONS.get(code, TRANSLATIONS["en"])
    return table.get(key, TRANSLATIONS["en"].get(key, key))
