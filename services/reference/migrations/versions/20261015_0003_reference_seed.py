"""Reference Data seed (Implementation Blueprint seeds, reference_db)

The eleven lists named by the Blueprint, plus one approval policy per list. Policies are
seeded OFF (v5: "any reference list, off by default"); switching Maker-Checker on for a
list is a data change. Codes are stable public keys: never changed or reused.
lookup_values starts empty (v5: optional).

Revision ID: 0003_reference_seed
Revises: 0002_reference_lists
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

from js_core.ids import uuid7

revision = "0003_reference_seed"
down_revision = "0002_reference_lists"
branch_labels = None
depends_on = None

# States and union territories of India: (code, name, Hindi name)
STATES = [
    ("AN", "Andaman and Nicobar Islands", "अंडमान और निकोबार द्वीपसमूह"), ("AP", "Andhra Pradesh", "आंध्र प्रदेश"),
    ("AR", "Arunachal Pradesh", "अरुणाचल प्रदेश"), ("AS", "Assam", "असम"), ("BR", "Bihar", "बिहार"),
    ("CH", "Chandigarh", "चंडीगढ़"), ("CT", "Chhattisgarh", "छत्तीसगढ़"),
    ("DH", "Dadra and Nagar Haveli and Daman and Diu", "दादरा और नगर हवेली और दमन और दीव"), ("DL", "Delhi", "दिल्ली"),
    ("GA", "Goa", "गोवा"), ("GJ", "Gujarat", "गुजरात"), ("HR", "Haryana", "हरियाणा"),
    ("HP", "Himachal Pradesh", "हिमाचल प्रदेश"), ("JK", "Jammu and Kashmir", "जम्मू और कश्मीर"),
    ("JH", "Jharkhand", "झारखंड"), ("KA", "Karnataka", "कर्नाटक"), ("KL", "Kerala", "केरल"),
    ("LA", "Ladakh", "लद्दाख"), ("LD", "Lakshadweep", "लक्षद्वीप"), ("MP", "Madhya Pradesh", "मध्य प्रदेश"),
    ("MH", "Maharashtra", "महाराष्ट्र"), ("MN", "Manipur", "मणिपुर"), ("ML", "Meghalaya", "मेघालय"),
    ("MZ", "Mizoram", "मिज़ोरम"), ("NL", "Nagaland", "नागालैंड"), ("OR", "Odisha", "ओडिशा"),
    ("PY", "Puducherry", "पुदुच्चेरी"), ("PB", "Punjab", "पंजाब"), ("RJ", "Rajasthan", "राजस्थान"),
    ("SK", "Sikkim", "सिक्किम"), ("TN", "Tamil Nadu", "तमिलनाडु"), ("TG", "Telangana", "तेलंगाना"),
    ("TR", "Tripura", "त्रिपुरा"), ("UP", "Uttar Pradesh", "उत्तर प्रदेश"), ("UT", "Uttarakhand", "उत्तराखंड"),
    ("WB", "West Bengal", "पश्चिम बंगाल"),
]

# Major cities: (code, name, state code)
CITIES = [
    ("VISAKHAPATNAM", "Visakhapatnam", "AP"), ("VIJAYAWADA", "Vijayawada", "AP"), ("GUWAHATI", "Guwahati", "AS"),
    ("PATNA", "Patna", "BR"), ("CHANDIGARH", "Chandigarh", "CH"), ("RAIPUR", "Raipur", "CT"),
    ("NEW_DELHI", "New Delhi", "DL"), ("PANAJI", "Panaji", "GA"), ("AHMEDABAD", "Ahmedabad", "GJ"),
    ("SURAT", "Surat", "GJ"), ("VADODARA", "Vadodara", "GJ"), ("GURUGRAM", "Gurugram", "HR"),
    ("FARIDABAD", "Faridabad", "HR"), ("SHIMLA", "Shimla", "HP"), ("SRINAGAR", "Srinagar", "JK"),
    ("JAMMU", "Jammu", "JK"), ("RANCHI", "Ranchi", "JH"), ("JAMSHEDPUR", "Jamshedpur", "JH"),
    ("BENGALURU", "Bengaluru", "KA"), ("MYSURU", "Mysuru", "KA"), ("MANGALURU", "Mangaluru", "KA"),
    ("KOCHI", "Kochi", "KL"), ("THIRUVANANTHAPURAM", "Thiruvananthapuram", "KL"), ("BHOPAL", "Bhopal", "MP"),
    ("INDORE", "Indore", "MP"), ("MUMBAI", "Mumbai", "MH"), ("PUNE", "Pune", "MH"), ("NAGPUR", "Nagpur", "MH"),
    ("NASHIK", "Nashik", "MH"), ("THANE", "Thane", "MH"), ("NAVI_MUMBAI", "Navi Mumbai", "MH"),
    ("CHHATRAPATI_SAMBHAJINAGAR", "Chhatrapati Sambhajinagar", "MH"), ("IMPHAL", "Imphal", "MN"),
    ("SHILLONG", "Shillong", "ML"), ("BHUBANESWAR", "Bhubaneswar", "OR"), ("PUDUCHERRY", "Puducherry", "PY"),
    ("LUDHIANA", "Ludhiana", "PB"), ("AMRITSAR", "Amritsar", "PB"), ("JAIPUR", "Jaipur", "RJ"),
    ("JODHPUR", "Jodhpur", "RJ"), ("CHENNAI", "Chennai", "TN"), ("COIMBATORE", "Coimbatore", "TN"),
    ("MADURAI", "Madurai", "TN"), ("HYDERABAD", "Hyderabad", "TG"), ("WARANGAL", "Warangal", "TG"),
    ("AGARTALA", "Agartala", "TR"), ("LUCKNOW", "Lucknow", "UP"), ("NOIDA", "Noida", "UP"),
    ("GHAZIABAD", "Ghaziabad", "UP"), ("KANPUR", "Kanpur", "UP"), ("VARANASI", "Varanasi", "UP"),
    ("DEHRADUN", "Dehradun", "UT"), ("KOLKATA", "Kolkata", "WB"), ("DURGAPUR", "Durgapur", "WB"),
]

INDUSTRIES = [
    ("IT_SOFTWARE", "IT & Software"), ("BPO_CUSTOMER_SERVICE", "BPO & Customer Service"),
    ("BANKING_FINANCE", "Banking & Financial Services"), ("INSURANCE", "Insurance"),
    ("RETAIL_ECOMMERCE", "Retail & E-commerce"), ("MANUFACTURING", "Manufacturing"),
    ("HEALTHCARE", "Healthcare & Pharma"), ("EDUCATION", "Education & Training"),
    ("LOGISTICS", "Logistics & Supply Chain"), ("CONSTRUCTION_REAL_ESTATE", "Construction & Real Estate"),
    ("HOSPITALITY", "Hospitality & Travel"), ("TELECOM", "Telecom"), ("AUTOMOBILE", "Automobile"),
    ("FMCG", "FMCG"), ("MEDIA_MARKETING", "Media, Marketing & Advertising"), ("GOVERNMENT", "Government & Public Sector"),
    ("AGRICULTURE", "Agriculture"), ("OTHER", "Other"),
]

# (code, name, roles: [(code, name)])
CATEGORIES = [
    ("SALES_BUSINESS_DEV", "Sales & Business Development", [("SALES_EXECUTIVE", "Sales Executive"),
        ("FIELD_SALES", "Field Sales Executive"), ("BUSINESS_DEVELOPMENT_EXECUTIVE", "Business Development Executive"),
        ("TELESALES", "Telesales Executive")]),
    ("CUSTOMER_SUPPORT", "Customer Support", [("CUSTOMER_SUPPORT_EXECUTIVE", "Customer Support Executive"),
        ("VOICE_PROCESS", "Voice Process Associate"), ("NON_VOICE_PROCESS", "Non-Voice Process Associate")]),
    ("IT_SOFTWARE", "IT & Software", [("SOFTWARE_DEVELOPER", "Software Developer"),
        ("FRONTEND_DEVELOPER", "Frontend Developer"), ("BACKEND_DEVELOPER", "Backend Developer"),
        ("QA_TESTER", "QA / Tester"), ("IT_SUPPORT", "IT Support Engineer"), ("DATA_ANALYST", "Data Analyst")]),
    ("ACCOUNTS_FINANCE", "Accounts & Finance", [("ACCOUNTANT", "Accountant"),
        ("ACCOUNTS_ASSISTANT", "Accounts Assistant"), ("FINANCE_EXECUTIVE", "Finance Executive")]),
    ("HR_ADMIN", "HR & Administration", [("HR_EXECUTIVE", "HR Executive"), ("RECRUITER", "Recruiter"),
        ("ADMIN_EXECUTIVE", "Admin Executive"), ("RECEPTIONIST", "Receptionist")]),
    ("MARKETING", "Marketing", [("DIGITAL_MARKETING_EXECUTIVE", "Digital Marketing Executive"),
        ("CONTENT_WRITER", "Content Writer"), ("GRAPHIC_DESIGNER", "Graphic Designer")]),
    ("OPERATIONS", "Operations & Back Office", [("BACK_OFFICE_EXECUTIVE", "Back Office Executive"),
        ("DATA_ENTRY_OPERATOR", "Data Entry Operator"), ("OPERATIONS_EXECUTIVE", "Operations Executive")]),
    ("LOGISTICS_DELIVERY", "Logistics & Delivery", [("DELIVERY_EXECUTIVE", "Delivery Executive"),
        ("WAREHOUSE_ASSOCIATE", "Warehouse Associate"), ("DRIVER", "Driver")]),
    ("SKILLED_TRADES", "Skilled & Technical Trades", [("ELECTRICIAN", "Electrician"), ("TECHNICIAN", "Technician"),
        ("MACHINE_OPERATOR", "Machine Operator"), ("WELDER", "Welder")]),
    ("HEALTHCARE", "Healthcare", [("NURSE", "Nurse"), ("PHARMACIST", "Pharmacist"),
        ("LAB_TECHNICIAN", "Lab Technician")]),
    ("TEACHING", "Teaching & Training", [("TEACHER", "Teacher"), ("TRAINER", "Trainer")]),
    ("HOSPITALITY", "Hospitality", [("COOK", "Cook / Chef"), ("WAITER", "Waiter / Steward"),
        ("FRONT_DESK", "Front Desk Executive")]),
    ("SECURITY_FACILITY", "Security & Facility", [("SECURITY_GUARD", "Security Guard"),
        ("HOUSEKEEPING", "Housekeeping Staff")]),
]

SKILLS = [
    ("COMMUNICATION", "Communication"), ("ENGLISH_SPEAKING", "English Speaking"), ("HINDI_SPEAKING", "Hindi Speaking"),
    ("MS_EXCEL", "MS Excel"), ("MS_OFFICE", "MS Office"), ("TALLY", "Tally"), ("GST", "GST"), ("TYPING", "Typing"),
    ("NEGOTIATION", "Negotiation"), ("CUSTOMER_HANDLING", "Customer Handling"), ("LEAD_GENERATION", "Lead Generation"),
    ("COLD_CALLING", "Cold Calling"), ("TEAM_MANAGEMENT", "Team Management"), ("PROBLEM_SOLVING", "Problem Solving"),
    ("PYTHON", "Python"), ("JAVA", "Java"), ("JAVASCRIPT", "JavaScript"), ("REACT", "React"), ("SQL", "SQL"),
    ("HTML_CSS", "HTML & CSS"), ("MANUAL_TESTING", "Manual Testing"), ("DATA_ANALYSIS", "Data Analysis"),
    ("POWER_BI", "Power BI"), ("SEO", "SEO"), ("SOCIAL_MEDIA_MARKETING", "Social Media Marketing"),
    ("CONTENT_WRITING", "Content Writing"), ("GRAPHIC_DESIGN", "Graphic Design"), ("RECRUITMENT", "Recruitment"),
    ("PAYROLL", "Payroll"), ("ACCOUNTING", "Accounting"), ("DRIVING_LICENCE", "Driving Licence"),
    ("TWO_WHEELER", "Two-Wheeler Riding"), ("INVENTORY_MANAGEMENT", "Inventory Management"),
    ("ELECTRICAL_WIRING", "Electrical Wiring"), ("WELDING", "Welding"), ("COOKING", "Cooking"),
    ("FIRST_AID", "First Aid"), ("PATIENT_CARE", "Patient Care"), ("TEACHING", "Teaching"),
]

EDUCATION = [  # (code, name, level_rank)
    ("BELOW_10TH", "Below 10th", 1), ("10TH", "10th Pass", 2), ("12TH", "12th Pass", 3), ("ITI", "ITI", 3),
    ("DIPLOMA", "Diploma", 4), ("GRADUATE", "Graduate", 5), ("POST_GRADUATE", "Post Graduate", 6),
    ("DOCTORATE", "Doctorate", 7),
]

EXPERIENCE = [  # (code, name, min_months, max_months)
    ("FRESHER", "Fresher", 0, 6), ("0_1_YEARS", "Less than 1 year", 0, 12), ("1_2_YEARS", "1–2 years", 12, 24),
    ("2_5_YEARS", "2–5 years", 24, 60), ("5_10_YEARS", "5–10 years", 60, 120), ("10_PLUS_YEARS", "10+ years", 120, None),
]

JOB_TYPES = [("FULL_TIME", "Full-time"), ("PART_TIME", "Part-time"), ("CONTRACT", "Contract"),
             ("INTERNSHIP", "Internship"), ("TEMPORARY", "Temporary"), ("FREELANCE", "Freelance")]
WORK_MODES = [("ON_SITE", "Work from office"), ("REMOTE", "Work from home"), ("HYBRID", "Hybrid"),
              ("FIELD", "Field work")]
PAY_TYPES = [("MONTHLY", "Per month"), ("ANNUAL", "Per year"), ("DAILY", "Per day"), ("HOURLY", "Per hour"),
             ("FIXED", "Fixed (project)")]

LISTS = ["states", "cities", "industries", "job_categories", "job_roles", "skills", "education_levels",
         "experience_bands", "job_types", "work_modes", "pay_types", "lookup_values"]


def upgrade() -> None:
    conn = op.get_bind()

    def insert(table: str, **values) -> object:
        values.setdefault("id", uuid7())
        cols = ", ".join(values)
        conn.execute(sa.text(f"INSERT INTO {table} ({cols}) VALUES ({', '.join(':' + c for c in values)})"), values)
        return values["id"]

    state_ids = {code: insert("states", code=code, name=name, name_hi=hi, sort_order=i * 10)
                 for i, (code, name, hi) in enumerate(STATES)}
    for i, (code, name, state) in enumerate(CITIES):
        insert("cities", code=code, name=name, state_id=state_ids[state], sort_order=i * 10)
    for i, (code, name) in enumerate(INDUSTRIES):
        insert("industries", code=code, name=name, sort_order=i * 10)
    for i, (code, name, roles) in enumerate(CATEGORIES):
        category_id = insert("job_categories", code=code, name=name, sort_order=i * 10)
        for j, (role_code, role_name) in enumerate(roles):
            insert("job_roles", code=role_code, name=role_name, job_category_id=category_id, sort_order=j * 10)
    for i, (code, name) in enumerate(SKILLS):
        insert("skills", code=code, name=name, sort_order=i * 10)
    for i, (code, name, rank) in enumerate(EDUCATION):
        insert("education_levels", code=code, name=name, level_rank=rank, sort_order=i * 10)
    for i, (code, name, low, high) in enumerate(EXPERIENCE):
        insert("experience_bands", code=code, name=name, min_months=low, max_months=high, sort_order=i * 10)
    for table, rows in (("job_types", JOB_TYPES), ("work_modes", WORK_MODES), ("pay_types", PAY_TYPES)):
        for i, (code, name) in enumerate(rows):
            insert(table, code=code, name=name, sort_order=i * 10)
    for name in LISTS:
        insert("approval_policies", entity_type=name.upper(), is_enabled=False,
               maker_permission_code="REFERENCE.EDIT", checker_permission_code="REFERENCE.APPROVE")


def downgrade() -> None:
    # Reversible only on a database that holds nothing but the seed (fresh environments).
    for table in ("approval_policies", "job_roles", "job_categories", "cities", "states", "industries", "skills",
                  "education_levels", "experience_bands", "job_types", "work_modes", "pay_types"):
        op.execute(f"DELETE FROM {table}")
