"""Lab test reference data: optimal ranges, system groupings, plain-language explanations."""


# System groupings — defines display order and which markers belong to each group.
# Markers not found in any group fall into "Other".
SYSTEMS = {
    "Lipid Panel": [
        "Total Cholesterol", "HDL Cholesterol", "LDL Cholesterol",
        "Non-HDL Cholesterol", "Triglycerides",
    ],
    "Metabolic Panel": [
        "Glucose", "BUN", "Creatinine", "eGFR", "Sodium", "Potassium",
        "Chloride", "CO2", "Calcium", "Anion Gap", "BUN/Creatinine Ratio",
    ],
    "Complete Blood Count": [
        "WBC", "RBC", "Hemoglobin", "Hematocrit", "MCV", "MCH", "MCHC",
        "RDW", "Platelets", "MPV",
        "Neutrophils %", "Neutrophils", "Neutrophils (abs)",
        "Lymphocytes %", "Lymphocytes", "Lymphocytes (abs)",
        "Monocytes %", "Monocytes", "Monocytes (abs)",
        "Eosinophils %", "Eosinophils", "Eosinophils (abs)",
        "Basophils %", "Basophils", "Basophils (abs)",
    ],
    "Liver Panel": [
        "ALT", "AST", "ALP", "Total Bilirubin", "Albumin",
        "Total Protein", "Globulin",
    ],
    "Thyroid": [
        "TSH", "Free T4",
    ],
    "Hormones": [
        "Testosterone", "FSH", "LH",
    ],
    "Vitamins & Minerals": [
        "Vitamin D", "Vitamin B12", "Ferritin",
    ],
    "Coagulation": [
        "PT", "INR", "aPTT",
    ],
    "Other": [
        "HbA1c", "Homocysteine",
    ],
}

# Build reverse lookup: marker name -> primary system
_MARKER_TO_SYSTEM = {}
for _sys, _markers in SYSTEMS.items():
    for _m in _markers:
        if _m not in _MARKER_TO_SYSTEM:
            _MARKER_TO_SYSTEM[_m] = _sys


# Marker reference data keyed by canonical name.
# - optimal: (low, high) — tighter than lab "normal"; None = open-ended
# - unit: expected US unit after conversion
# - what: one sentence on what it measures
# - high/low: one sentence on what out-of-range means
# - optimal_note: brief guidance
MARKERS = {
    # ── Lipid Panel ──────────────────────────────────────────────
    "Total Cholesterol": {
        "optimal": (None, 200),
        "unit": "mg/dL",
        "what": "Sum of all cholesterol in your blood (HDL + LDL + others).",
        "high": "Elevated total cholesterol raises cardiovascular risk over time.",
        "low": "Very low cholesterol may indicate malnutrition or liver dysfunction.",
        "optimal_note": "Under 200 is desirable; under 150 is associated with lowest CV risk.",
    },
    "HDL Cholesterol": {
        "optimal": (60, None),
        "unit": "mg/dL",
        "what": "\"Good\" cholesterol — carries cholesterol away from arteries back to the liver.",
        "high": "Higher HDL is generally protective; very high levels (>100) are rare and benign.",
        "low": "Low HDL increases heart disease risk regardless of LDL levels.",
        "optimal_note": "Above 60 is protective; below 40 (men) or 50 (women) is a risk factor.",
    },
    "LDL Cholesterol": {
        "optimal": (None, 100),
        "unit": "mg/dL",
        "what": "\"Bad\" cholesterol — deposits cholesterol in artery walls.",
        "high": "Elevated LDL is the primary driver of atherosclerosis and heart disease.",
        "low": "Very low LDL is generally fine and associated with lower CV risk.",
        "optimal_note": "Under 100 is optimal; under 70 is recommended if you have CV risk factors.",
    },
    "Non-HDL Cholesterol": {
        "optimal": (None, 130),
        "unit": "mg/dL",
        "what": "Total cholesterol minus HDL — captures all atherogenic particles.",
        "high": "Elevated non-HDL is a strong predictor of cardiovascular events.",
        "low": "Low non-HDL indicates low atherogenic burden.",
        "optimal_note": "Under 130 is desirable; a better predictor than LDL alone.",
    },
    "Triglycerides": {
        "optimal": (None, 150),
        "unit": "mg/dL",
        "what": "Fat in your blood, mainly from recent food intake.",
        "high": "High triglycerides contribute to arterial plaque and raise pancreatitis risk.",
        "low": "Very low triglycerides are generally not a concern.",
        "optimal_note": "Under 150 is normal; under 100 is ideal. Strongly affected by fasting status.",
    },

    # ── Metabolic Panel ──────────────────────────────────────────
    "Glucose": {
        "optimal": (70, 99),
        "unit": "mg/dL",
        "what": "Blood sugar level, your body's primary energy source.",
        "high": "Elevated fasting glucose may indicate prediabetes or diabetes.",
        "low": "Low blood sugar can cause dizziness, confusion, and shakiness.",
        "optimal_note": "70-99 fasting is normal; 100-125 is prediabetes territory.",
    },
    "BUN": {
        "optimal": (7, 20),
        "unit": "mg/dL",
        "what": "Blood urea nitrogen — a waste product from protein metabolism filtered by kidneys.",
        "high": "Elevated BUN may indicate kidney dysfunction, dehydration, or high protein intake.",
        "low": "Low BUN can indicate liver disease or low protein diet.",
        "optimal_note": "7-20 is the standard range; interpret alongside creatinine.",
    },
    "Creatinine": {
        "optimal": (0.7, 1.2),
        "unit": "mg/dL",
        "what": "Waste product from muscle metabolism — a key indicator of kidney function.",
        "high": "Elevated creatinine suggests the kidneys aren't filtering efficiently.",
        "low": "Low creatinine may reflect low muscle mass or advanced liver disease.",
        "optimal_note": "0.7-1.2 for men; muscular individuals may run slightly higher.",
    },
    "eGFR": {
        "optimal": (90, None),
        "unit": "mL/min/1.73m^2",
        "what": "Estimated glomerular filtration rate — how well your kidneys filter waste.",
        "high": "Very high eGFR is normal and not a concern.",
        "low": "Low eGFR indicates reduced kidney function; below 60 warrants monitoring.",
        "optimal_note": "Above 90 is normal; 60-89 may be early kidney disease if other signs exist.",
    },
    "Sodium": {
        "optimal": (136, 145),
        "unit": "mmol/L",
        "what": "Electrolyte critical for fluid balance, nerve function, and blood pressure.",
        "high": "High sodium (hypernatremia) usually means dehydration.",
        "low": "Low sodium (hyponatremia) can cause confusion, nausea, and in severe cases, seizures.",
        "optimal_note": "136-145 is the normal range; usually shifts with hydration status.",
    },
    "Potassium": {
        "optimal": (3.5, 5.0),
        "unit": "mmol/L",
        "what": "Electrolyte essential for heart rhythm, muscle contraction, and nerve signals.",
        "high": "High potassium (hyperkalemia) can cause dangerous heart rhythm changes.",
        "low": "Low potassium (hypokalemia) causes muscle weakness, cramps, and irregular heartbeat.",
        "optimal_note": "3.5-5.0 is normal; both extremes are medically significant.",
    },
    "Chloride": {
        "optimal": (98, 106),
        "unit": "mmol/L",
        "what": "Electrolyte that helps maintain fluid balance and acid-base equilibrium.",
        "high": "High chloride often accompanies dehydration or metabolic acidosis.",
        "low": "Low chloride may indicate metabolic alkalosis or over-hydration.",
        "optimal_note": "98-106 is normal; usually interpreted alongside sodium and CO2.",
    },
    "CO2": {
        "optimal": (23, 29),
        "unit": "mmol/L",
        "what": "Bicarbonate level — reflects your body's acid-base balance.",
        "high": "Elevated CO2 may indicate metabolic alkalosis or respiratory compensation.",
        "low": "Low CO2 suggests metabolic acidosis, which can have many causes.",
        "optimal_note": "23-29 is normal; changes often accompany kidney or lung issues.",
    },
    "Calcium": {
        "optimal": (8.5, 10.5),
        "unit": "mg/dL",
        "what": "Essential mineral for bones, heart rhythm, nerve function, and blood clotting.",
        "high": "High calcium (hypercalcemia) may indicate parathyroid issues or vitamin D excess.",
        "low": "Low calcium can cause muscle cramps, tingling, and abnormal heart rhythms.",
        "optimal_note": "8.5-10.5 is normal; always interpret with albumin levels.",
    },
    "Anion Gap": {
        "optimal": (4, 12),
        "unit": "mmol/L",
        "what": "Calculated gap between measured cations and anions — helps identify acid-base disorders.",
        "high": "Elevated anion gap suggests metabolic acidosis (e.g., diabetic ketoacidosis, lactic acidosis).",
        "low": "Low anion gap is uncommon and may indicate low albumin or lab error.",
        "optimal_note": "4-12 is typical; mainly useful for diagnosing metabolic acidosis.",
    },
    "BUN/Creatinine Ratio": {
        "optimal": (10, 20),
        "unit": "ratio",
        "what": "Ratio of BUN to creatinine — helps distinguish kidney issues from dehydration.",
        "high": "High ratio suggests dehydration, GI bleeding, or high protein intake rather than kidney disease.",
        "low": "Low ratio may indicate liver disease or low protein diet.",
        "optimal_note": "10-20 is normal; >20 often points to dehydration.",
    },

    # ── Complete Blood Count ─────────────────────────────────────
    "WBC": {
        "optimal": (4.5, 11.0),
        "unit": "10^3/uL",
        "what": "White blood cell count — your immune system's frontline defenders.",
        "high": "Elevated WBC (leukocytosis) usually indicates infection, inflammation, or stress.",
        "low": "Low WBC (leukopenia) may mean a weakened immune system or bone marrow issue.",
        "optimal_note": "4.5-11.0 is normal; exercise and stress can cause temporary spikes.",
    },
    "RBC": {
        "optimal": (4.5, 5.5),
        "unit": "10^6/uL",
        "what": "Red blood cell count — cells that carry oxygen throughout your body.",
        "high": "High RBC (polycythemia) may indicate dehydration, lung disease, or living at high altitude.",
        "low": "Low RBC (anemia) means reduced oxygen-carrying capacity — causes fatigue and weakness.",
        "optimal_note": "4.5-5.5 for men, 4.0-5.0 for women.",
    },
    "Hemoglobin": {
        "optimal": (13.5, 17.5),
        "unit": "g/dL",
        "what": "Protein in red blood cells that carries oxygen — the primary measure of anemia.",
        "high": "High hemoglobin may indicate dehydration or polycythemia.",
        "low": "Low hemoglobin (anemia) causes fatigue, shortness of breath, and pale skin.",
        "optimal_note": "13.5-17.5 for men, 12.0-16.0 for women.",
    },
    "Hematocrit": {
        "optimal": (38.3, 48.6),
        "unit": "%",
        "what": "Percentage of blood volume occupied by red blood cells.",
        "high": "High hematocrit may indicate dehydration or polycythemia vera.",
        "low": "Low hematocrit suggests anemia or blood loss.",
        "optimal_note": "38-49% for men, 36-44% for women.",
    },
    "MCV": {
        "optimal": (80, 100),
        "unit": "fL",
        "what": "Mean corpuscular volume — the average size of your red blood cells.",
        "high": "Large red cells (macrocytosis) may indicate B12/folate deficiency or liver disease.",
        "low": "Small red cells (microcytosis) often indicate iron deficiency or thalassemia.",
        "optimal_note": "80-100 fL is normal; helps classify the type of anemia.",
    },
    "MCH": {
        "optimal": (27, 33),
        "unit": "pg",
        "what": "Mean corpuscular hemoglobin — average amount of hemoglobin per red blood cell.",
        "high": "High MCH usually accompanies macrocytic anemias (B12/folate deficiency).",
        "low": "Low MCH accompanies iron deficiency and thalassemia.",
        "optimal_note": "27-33 pg; closely tracks with MCV.",
    },
    "MCHC": {
        "optimal": (32, 36),
        "unit": "g/dL",
        "what": "Mean corpuscular hemoglobin concentration — hemoglobin density in red blood cells.",
        "high": "High MCHC can indicate hereditary spherocytosis or lab artifact.",
        "low": "Low MCHC typically seen in iron deficiency anemia.",
        "optimal_note": "32-36 g/dL is normal.",
    },
    "RDW": {
        "optimal": (11.5, 14.5),
        "unit": "%",
        "what": "Red cell distribution width — variation in red blood cell size.",
        "high": "High RDW means uneven red cell sizes, often seen in iron or B12 deficiency.",
        "low": "Low RDW is normal — it means your red cells are uniform in size.",
        "optimal_note": "11.5-14.5%; elevated RDW + anemia helps pinpoint the cause.",
    },
    "Platelets": {
        "optimal": (150, 400),
        "unit": "10^3/uL",
        "what": "Cell fragments essential for blood clotting.",
        "high": "High platelets (thrombocytosis) may increase clotting risk; often reactive to infection/inflammation.",
        "low": "Low platelets (thrombocytopenia) increase bleeding risk.",
        "optimal_note": "150-400 is normal; both extremes warrant follow-up.",
    },
    "MPV": {
        "optimal": (7.5, 11.5),
        "unit": "fL",
        "what": "Mean platelet volume — average size of your platelets.",
        "high": "Large platelets may indicate active platelet production (bone marrow response).",
        "low": "Small platelets may suggest bone marrow suppression.",
        "optimal_note": "7.5-11.5 fL; useful when interpreting abnormal platelet counts.",
    },
    "Neutrophils %": {
        "optimal": (40, 70),
        "unit": "%",
        "what": "Percentage of white blood cells that are neutrophils — first responders to bacterial infection.",
        "high": "High neutrophil percentage suggests bacterial infection, inflammation, or stress.",
        "low": "Low neutrophils may increase susceptibility to infections.",
        "optimal_note": "40-70% of WBC is normal.",
    },
    "Neutrophils": {
        "optimal": (1.8, 7.7),
        "unit": "10^3/uL",
        "what": "Absolute neutrophil count — your body's primary bacterial defense cells.",
        "high": "Elevated neutrophils typically indicate active infection or inflammation.",
        "low": "Low neutrophils (neutropenia) raise infection risk.",
        "optimal_note": "1.8-7.7 is normal; below 1.0 is clinically significant.",
    },
    "Neutrophils (abs)": {
        "optimal": (1.8, 7.7),
        "unit": "10^3/uL",
        "what": "Absolute neutrophil count — your body's primary bacterial defense cells.",
        "high": "Elevated neutrophils typically indicate active infection or inflammation.",
        "low": "Low neutrophils (neutropenia) raise infection risk.",
        "optimal_note": "1.8-7.7 is normal; below 1.0 is clinically significant.",
    },
    "Lymphocytes %": {
        "optimal": (20, 40),
        "unit": "%",
        "what": "Percentage of white blood cells that are lymphocytes — key players in immune memory and viral defense.",
        "high": "High lymphocytes often indicate viral infection or chronic immune stimulation.",
        "low": "Low lymphocytes may indicate immune suppression.",
        "optimal_note": "20-40% of WBC is normal.",
    },
    "Lymphocytes": {
        "optimal": (1.0, 4.8),
        "unit": "10^3/uL",
        "what": "Absolute lymphocyte count — includes T cells, B cells, and NK cells.",
        "high": "Elevated lymphocytes often indicate viral infection.",
        "low": "Low lymphocytes may indicate immune compromise.",
        "optimal_note": "1.0-4.8 is normal.",
    },
    "Lymphocytes (abs)": {
        "optimal": (1.0, 4.8),
        "unit": "10^3/uL",
        "what": "Absolute lymphocyte count — includes T cells, B cells, and NK cells.",
        "high": "Elevated lymphocytes often indicate viral infection.",
        "low": "Low lymphocytes may indicate immune compromise.",
        "optimal_note": "1.0-4.8 is normal.",
    },
    "Monocytes %": {
        "optimal": (2, 8),
        "unit": "%",
        "what": "Percentage of white blood cells that are monocytes — involved in chronic inflammation and immune cleanup.",
        "high": "Elevated monocytes may indicate chronic infection, autoimmune conditions, or recovery from acute illness.",
        "low": "Low monocytes are generally not clinically significant on their own.",
        "optimal_note": "2-8% of WBC is normal.",
    },
    "Monocytes": {
        "optimal": (0.2, 0.8),
        "unit": "10^3/uL",
        "what": "Absolute monocyte count — cells that become macrophages in tissues.",
        "high": "Elevated monocytes suggest chronic inflammation or infection.",
        "low": "Low monocytes are usually not concerning.",
        "optimal_note": "0.2-0.8 is normal.",
    },
    "Monocytes (abs)": {
        "optimal": (0.2, 0.8),
        "unit": "10^3/uL",
        "what": "Absolute monocyte count — cells that become macrophages in tissues.",
        "high": "Elevated monocytes suggest chronic inflammation or infection.",
        "low": "Low monocytes are usually not concerning.",
        "optimal_note": "0.2-0.8 is normal.",
    },
    "Eosinophils %": {
        "optimal": (1, 4),
        "unit": "%",
        "what": "Percentage of white blood cells that are eosinophils — involved in allergic responses and parasitic defense.",
        "high": "High eosinophils suggest allergies, asthma, or parasitic infection.",
        "low": "Low eosinophils are normal and not a concern.",
        "optimal_note": "1-4% of WBC is normal.",
    },
    "Eosinophils": {
        "optimal": (0.0, 0.5),
        "unit": "10^3/uL",
        "what": "Absolute eosinophil count — cells active in allergy and parasite defense.",
        "high": "Elevated eosinophils suggest allergic reaction or parasitic infection.",
        "low": "Low eosinophils are normal.",
        "optimal_note": "0.0-0.5 is normal.",
    },
    "Eosinophils (abs)": {
        "optimal": (0.0, 0.5),
        "unit": "10^3/uL",
        "what": "Absolute eosinophil count — cells active in allergy and parasite defense.",
        "high": "Elevated eosinophils suggest allergic reaction or parasitic infection.",
        "low": "Low eosinophils are normal.",
        "optimal_note": "0.0-0.5 is normal.",
    },
    "Basophils %": {
        "optimal": (0, 1),
        "unit": "%",
        "what": "Percentage of white blood cells that are basophils — involved in allergic and inflammatory responses.",
        "high": "Elevated basophils may indicate allergic reactions or certain blood disorders.",
        "low": "Low basophils are normal — they're the rarest white blood cell type.",
        "optimal_note": "0-1% of WBC is normal.",
    },
    "Basophils": {
        "optimal": (0.0, 0.1),
        "unit": "10^3/uL",
        "what": "Absolute basophil count — rarest white blood cells, involved in allergic responses.",
        "high": "Elevated basophils may indicate allergy, inflammation, or rarely, blood disorders.",
        "low": "Low basophils are normal.",
        "optimal_note": "0.0-0.1 is normal.",
    },
    "Basophils (abs)": {
        "optimal": (0.0, 0.1),
        "unit": "10^3/uL",
        "what": "Absolute basophil count — rarest white blood cells, involved in allergic responses.",
        "high": "Elevated basophils may indicate allergy, inflammation, or rarely, blood disorders.",
        "low": "Low basophils are normal.",
        "optimal_note": "0.0-0.1 is normal.",
    },

    # ── Liver Panel ──────────────────────────────────────────────
    "ALT": {
        "optimal": (7, 35),
        "unit": "U/L",
        "what": "Alanine aminotransferase — a liver enzyme released when liver cells are damaged.",
        "high": "Elevated ALT is the most specific marker for liver cell injury (hepatitis, fatty liver, medications).",
        "low": "Low ALT is normal and not concerning.",
        "optimal_note": "7-35 U/L; even mild elevations warrant monitoring if persistent.",
    },
    "AST": {
        "optimal": (10, 35),
        "unit": "U/L",
        "what": "Aspartate aminotransferase — found in liver, heart, and muscle tissue.",
        "high": "Elevated AST may indicate liver damage, heart injury, or intense exercise.",
        "low": "Low AST is normal.",
        "optimal_note": "10-35 U/L; less liver-specific than ALT — can rise after heavy workouts.",
    },
    "ALP": {
        "optimal": (44, 147),
        "unit": "U/L",
        "what": "Alkaline phosphatase — an enzyme from liver and bone.",
        "high": "Elevated ALP may indicate bile duct obstruction, bone disorders, or liver disease.",
        "low": "Low ALP is uncommon and usually not significant.",
        "optimal_note": "44-147 U/L; elevated in growing children and pregnancy (normal).",
    },
    "Total Bilirubin": {
        "optimal": (0.1, 1.2),
        "unit": "mg/dL",
        "what": "Byproduct of red blood cell breakdown, processed by the liver.",
        "high": "Elevated bilirubin causes jaundice (yellowing) and may indicate liver or bile duct issues. Mild elevations are often Gilbert syndrome (benign).",
        "low": "Low bilirubin is normal.",
        "optimal_note": "0.1-1.2 mg/dL; mild elevations (1.2-3) in young men are often benign Gilbert syndrome.",
    },
    "Albumin": {
        "optimal": (3.5, 5.5),
        "unit": "g/dL",
        "what": "Most abundant blood protein — made by the liver, maintains fluid balance.",
        "high": "High albumin usually indicates dehydration.",
        "low": "Low albumin suggests liver disease, kidney loss, malnutrition, or chronic inflammation.",
        "optimal_note": "3.5-5.5 g/dL; a good marker of overall nutritional and liver status.",
    },
    "Total Protein": {
        "optimal": (6.0, 8.3),
        "unit": "g/dL",
        "what": "Combined albumin and globulin in your blood.",
        "high": "High total protein may indicate chronic infection, inflammation, or dehydration.",
        "low": "Low total protein suggests liver disease, kidney loss, or malnutrition.",
        "optimal_note": "6.0-8.3 g/dL.",
    },
    "Globulin": {
        "optimal": (2.0, 3.5),
        "unit": "g/dL",
        "what": "Group of proteins including antibodies — reflects immune system activity.",
        "high": "Elevated globulin may indicate chronic infection, inflammation, or immune disorders.",
        "low": "Low globulin may indicate immune deficiency.",
        "optimal_note": "2.0-3.5 g/dL; calculated as total protein minus albumin.",
    },

    # ── Thyroid ──────────────────────────────────────────────────
    "TSH": {
        "optimal": (0.5, 2.5),
        "unit": "uIU/mL",
        "what": "Thyroid-stimulating hormone — the master controller of thyroid function.",
        "high": "High TSH means your thyroid is underactive (hypothyroidism) — fatigue, weight gain, cold intolerance.",
        "low": "Low TSH means your thyroid is overactive (hyperthyroidism) — anxiety, weight loss, rapid heart rate.",
        "optimal_note": "Lab range goes to 4.5, but many practitioners consider 0.5-2.5 optimal.",
    },
    "Free T4": {
        "optimal": (0.8, 1.8),
        "unit": "ng/dL",
        "what": "Free thyroxine — the active form of the main thyroid hormone.",
        "high": "High free T4 indicates hyperthyroidism or over-replacement with thyroid medication.",
        "low": "Low free T4 confirms hypothyroidism, especially when TSH is elevated.",
        "optimal_note": "0.8-1.8 ng/dL; interpret alongside TSH.",
    },

    # ── Hormones ─────────────────────────────────────────────────
    "Testosterone": {
        "optimal": (400, 900),
        "unit": "ng/dL",
        "what": "Primary male sex hormone — critical for muscle, bone, mood, and energy.",
        "high": "Very high testosterone may indicate supplementation or rarely, tumors.",
        "low": "Low testosterone causes fatigue, low libido, muscle loss, and mood changes.",
        "optimal_note": "400-900 ng/dL for men (age-dependent); below 300 is clinically low.",
    },
    "FSH": {
        "optimal": (1.5, 12.4),
        "unit": "mIU/mL",
        "what": "Follicle-stimulating hormone — regulates sperm production in men.",
        "high": "Elevated FSH in men may indicate testicular dysfunction.",
        "low": "Low FSH may indicate pituitary issues.",
        "optimal_note": "1.5-12.4 mIU/mL for adult men.",
    },
    "LH": {
        "optimal": (1.7, 8.6),
        "unit": "mIU/mL",
        "what": "Luteinizing hormone — stimulates testosterone production.",
        "high": "Elevated LH with low testosterone suggests primary testicular failure.",
        "low": "Low LH with low testosterone suggests a pituitary or hypothalamic issue.",
        "optimal_note": "1.7-8.6 mIU/mL for adult men.",
    },

    # ── Vitamins & Minerals ──────────────────────────────────────
    "Vitamin D": {
        "optimal": (40, 60),
        "unit": "ng/mL",
        "what": "25-hydroxyvitamin D — essential for bone health, immune function, and mood.",
        "high": "Very high vitamin D (>100) can cause toxicity — nausea, kidney stones, calcium buildup.",
        "low": "Low vitamin D is extremely common and linked to fatigue, weak bones, and immune dysfunction.",
        "optimal_note": "Lab says 30+ is sufficient, but 40-60 is where most benefits are maximized.",
    },
    "Vitamin B12": {
        "optimal": (500, 1000),
        "unit": "pg/mL",
        "what": "Essential for nerve function, DNA synthesis, and red blood cell formation.",
        "high": "Very high B12 is usually from supplements and not harmful.",
        "low": "Low B12 causes fatigue, numbness/tingling, memory issues, and macrocytic anemia.",
        "optimal_note": "Lab says 200+ is normal, but 500+ is optimal. Deficiency is common in plant-based diets.",
    },
    "Ferritin": {
        "optimal": (30, 200),
        "unit": "ng/mL",
        "what": "Iron storage protein — the best single test for iron status.",
        "high": "High ferritin may indicate iron overload (hemochromatosis), inflammation, or liver disease.",
        "low": "Low ferritin means depleted iron stores — causes fatigue and eventually anemia.",
        "optimal_note": "30-200 for men; below 30 indicates iron depletion even if hemoglobin is normal.",
    },

    # ── Coagulation ──────────────────────────────────────────────
    "PT": {
        "optimal": (11, 13.5),
        "unit": "seconds",
        "what": "Prothrombin time — measures how long blood takes to clot via the extrinsic pathway.",
        "high": "Prolonged PT suggests clotting factor deficiency, liver disease, or anticoagulant use.",
        "low": "Short PT is generally not clinically significant.",
        "optimal_note": "11-13.5 seconds; mainly used to monitor warfarin therapy.",
    },
    "INR": {
        "optimal": (0.8, 1.1),
        "unit": "ratio",
        "what": "International normalized ratio — standardized measure of clotting time.",
        "high": "High INR means blood is slower to clot — increased bleeding risk.",
        "low": "Low INR means blood clots quickly — generally normal if not on anticoagulants.",
        "optimal_note": "0.8-1.1 for healthy adults; 2.0-3.0 is the target for patients on warfarin.",
    },
    "aPTT": {
        "optimal": (25, 35),
        "unit": "seconds",
        "what": "Activated partial thromboplastin time — measures the intrinsic clotting pathway.",
        "high": "Prolonged aPTT may indicate clotting factor deficiency or heparin therapy.",
        "low": "Short aPTT is generally not clinically significant.",
        "optimal_note": "25-35 seconds is normal.",
    },

    # ── Other ────────────────────────────────────────────────────
    "HbA1c": {
        "optimal": (None, 5.6),
        "unit": "%",
        "what": "Glycated hemoglobin — reflects your average blood sugar over the past 2-3 months.",
        "high": "Elevated HbA1c indicates prediabetes (5.7-6.4%) or diabetes (6.5%+).",
        "low": "Very low HbA1c may indicate frequent low blood sugar episodes.",
        "optimal_note": "Under 5.7% is normal; under 5.0% is associated with lowest metabolic risk.",
    },
    "Homocysteine": {
        "optimal": (5, 10),
        "unit": "umol/L",
        "what": "Amino acid linked to cardiovascular risk — elevated by B12/folate deficiency.",
        "high": "High homocysteine is an independent risk factor for heart disease and stroke.",
        "low": "Low homocysteine is not a concern.",
        "optimal_note": "Under 10 is optimal; above 15 significantly raises CV risk. B vitamins lower it.",
    },
}


def get_marker_info(name):
    """Return the MARKERS entry for a canonical name, or None."""
    return MARKERS.get(name)


def get_system_for_marker(name):
    """Return the primary system grouping for a marker."""
    return _MARKER_TO_SYSTEM.get(name, "Other")


def get_optimal_flag(name, value):
    """Return 'optimal', 'above_optimal', 'below_optimal', or 'unknown'.

    Compares value against the optimal range in MARKERS (which may be
    tighter than the lab's reference range).
    """
    info = MARKERS.get(name)
    if not info:
        return "unknown"

    low, high = info["optimal"]
    if low is not None and value < low:
        return "below_optimal"
    if high is not None and value > high:
        return "above_optimal"
    return "optimal"
