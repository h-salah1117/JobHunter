"""
src/ats_evaluator.py — Rule-based ATS evaluation logic for resumes.
Evaluates sections, word count, tech action verbs, metrics, and skills density.
"""

import re

# Tech action verbs (stems/words)
ACTION_VERBS = {
    'designed', 'developed', 'implemented', 'engineered', 'led', 'managed', 'optimized',
    'increased', 'improved', 'reduced', 'accelerated', 'architected', 'delivered',
    'built', 'created', 'deployed', 'automated', 'integrated', 'streamlined', 'conducted',
    'analyzed', 'programmed', 'authored', 'managed', 'supervised', 'directed', 'coordinated',
    'solved', 'resolved', 'formulated', 'executed', 'designed', 'conceptualized'
}

# Standard headings keywords
SECTION_PATTERNS = {
    'experience': r'(experience|employment|work history|professional history|career history|position|employment history)',
    'education': r'(education|university|academic|college|degree|qualification)',
    'skills': r'(skills|technologies|technical skills|languages|expertise|core competencies)',
    'contact': r'(contact|email|phone|address|linkedin|github|location)'
}

# Standard tech skills keywords to verify skills density
STANDARD_SKILLS = {
    'python', 'sql', 'r', 'java', 'c++', 'c#', 'javascript', 'typescript', 'html', 'css',
    'pytorch', 'tensorflow', 'keras', 'scikit-learn', 'pandas', 'numpy', 'scipy', 'matplotlib',
    'seaborn', 'spark', 'hadoop', 'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'git', 'github',
    'tableau', 'power bi', 'excel', 'mlops', 'langchain', 'llama', 'chromadb', 'mongodb', 'postgresql',
    'mysql', 'oracle', 'django', 'flask', 'fastapi', 'linux', 'bash', 'devops', 'ci/cd', 'jenkins'
}

def evaluate_resume_ats(cv_text: str) -> dict:
    """
    Deterministically evaluates a CV/resume text for ATS compatibility.
    Returns score (0-100), section scores, and advice logs in English and Arabic.
    """
    if not cv_text or not cv_text.strip():
        return {
            "ats_score": 0,
            "detected_skills": [],
            "missing_skills": [],
            "feedback_en": ["Resume text is empty. Please check your file."],
            "feedback_ar": ["ملف السيرة الذاتية فارغ. يرجى التأكد من محتوى الملف."],
            "summary_en": "Empty resume file provided.",
            "summary_ar": "ملف سيرة ذاتية فارغ."
        }

    # Normalize text
    text_lower = cv_text.lower()
    words = re.findall(r'\b\w+\b', text_lower)
    word_count = len(words)

    # 1. Section Completeness (Max 20 points)
    section_scores = {}
    sections_found = []
    sections_missing = []
    
    for section_name, pattern in SECTION_PATTERNS.items():
        match = re.search(pattern, text_lower)
        if match:
            section_scores[section_name] = 5
            sections_found.append(section_name)
        else:
            section_scores[section_name] = 0
            sections_missing.append(section_name)
            
    sections_score = sum(section_scores.values())  # Max 20

    # 2. Action Verbs Density (Max 20 points)
    found_verbs = [w for w in words if w in ACTION_VERBS]
    verbs_count = len(found_verbs)
    # Density score: 1 point per distinct action verb found, up to 20 points
    distinct_verbs = set(found_verbs)
    verbs_score = min(20, len(distinct_verbs) * 2)

    # 3. Quantifiable Metrics (Max 20 points)
    # Match numbers followed by %, +, $, £, or standard metrics keywords like "years", "million", "k"
    metrics_matches = re.findall(r'(\b\d+(?:\.\d+)?\s*(?:%|\+|\$|£|usd|gbp|years|million|k|x)\b)', text_lower)
    metrics_count = len(metrics_matches)
    metrics_score = min(20, metrics_count * 4) # 5 metrics gives full points

    # 4. Tech Skills Match (Max 20 points)
    detected_skills = [w for w in set(words) if w in STANDARD_SKILLS]
    # Format case nicely
    formatted_skills = []
    skill_case_map = {s.lower(): s for s in STANDARD_SKILLS}
    # capitalize some acronyms
    acronyms = {'sql', 'aws', 'gcp', 'css', 'html', 'mlops', 'ci/cd', 'bi', 'r', 'usd', 'gbp'}
    for s in detected_skills:
        clean_s = s.strip()
        if clean_s in acronyms:
            formatted_skills.append(clean_s.upper())
        elif clean_s == 'pytorch':
            formatted_skills.append('PyTorch')
        elif clean_s == 'tensorflow':
            formatted_skills.append('TensorFlow')
        elif clean_s == 'scikit-learn':
            formatted_skills.append('scikit-learn')
        elif clean_s == 'power bi':
            formatted_skills.append('Power BI')
        else:
            formatted_skills.append(clean_s.capitalize())
            
    skills_score = min(20, len(detected_skills) * 4) # 5 skills gives full points

    # 5. Length Suitability (Max 20 points)
    # Ideal range for single/double-page ATS resume is 300 to 1000 words
    if 300 <= word_count <= 900:
        length_score = 20
    elif 150 <= word_count < 300:
        length_score = 12
    elif 900 < word_count <= 1300:
        length_score = 15
    else:
        length_score = 5

    # Total ATS Score
    ats_score = sections_score + verbs_score + metrics_score + skills_score + length_score

    # Generate localized advice list
    feedback_en = []
    feedback_ar = []

    # Section advice
    if sections_missing:
        missing_str_en = ", ".join([s.capitalize() for s in sections_missing])
        feedback_en.append(f"Add explicit headings for missing sections: {missing_str_en}.")
        
        # Arabic translation mapping for section names
        ar_section_names = {
            'experience': 'الخبرات المهنية (Experience)',
            'education': 'التعليم والدراسة (Education)',
            'skills': 'المهارات التقنية (Skills)',
            'contact': 'معلومات الاتصال (Contact Info)'
        }
        missing_str_ar = " و ".join([ar_section_names[s] for s in sections_missing])
        feedback_ar.append(f"يا ريت تضيف عناوين واضحة للأقسام الناقصة دي: {missing_str_ar}.")

    # Verbs advice
    if verbs_score < 12:
        feedback_en.append("Use more strong professional action verbs (e.g. 'designed', 'optimized', 'automated') at the start of your bullet points.")
        feedback_ar.append("زود شوية أفعال حركية قوية (زي: صممت، طورت، أتمتت، حسّنت) في بداية نقط شرح مسؤولياتك عشان تبرز دورك.")

    # Metrics advice
    if metrics_score < 12:
        feedback_en.append("Quantify your achievements with numbers, percentages, or scale metrics (e.g., 'improved query performance by 40%').")
        feedback_ar.append("حاول توضح إنجازاتك بالأرقام والنسب المئوية (مثلاً: 'حسّنت سرعة قواعد البيانات بنسبة 40%' أو 'قدت فريق من 4 أفراد').")

    # Skills advice
    if skills_score < 12:
        feedback_en.append("List more technical skills and technologies relevant to your job target (e.g. Python, SQL, Docker).")
        feedback_ar.append("ضيف مهارات وأدوات تقنية أكتر بتستخدمها في مجالك (زي: Python, SQL, Docker) في قسم المهارات.")

    # Length advice
    if word_count < 250:
        feedback_en.append("Your resume is too brief. Expand on your project experience and responsibilities (aim for at least 300 words).")
        feedback_ar.append("السيرة الذاتية بتاعتك قصيرة شوية، حاول تكتب تفاصيل أكتر عن مشاريعك السابقة ومسؤولياتك عشان الـ ATS يفهم خبرتك.")
    elif word_count > 1100:
        feedback_en.append("Your resume is excessively long. Condense formatting to keep it within 1-2 pages (aim for under 1000 words).")
        feedback_ar.append("السيرة الذاتية طويلة زيادة عن اللزوم، حاول تلخصها عشان متزيدش عن صفحتين وتبان مرتبة أكتر لبرامج الفحص.")

    # General default tips if score is already high
    if not feedback_en:
        feedback_en.append("Ensure your CV is saved in PDF or DOCX format and avoids complex table nesting or sidebar column splits.")
        feedback_ar.append("سيرتك الذاتية ممتازة! تأكد دائمًا من حفظها بصيغة PDF وتجنب استخدام الجداول المعقدة أو الأعمدة المتعددة.")
    if len(feedback_en) < 3:
        feedback_en.append("Avoid placing essential contact info inside page headers or footers, as some ATS parsers ignore those areas.")
        feedback_ar.append("بلاش تحط معلومات الاتصال المهمة جوة الـ Header أو الـ Footer لأن بعض برامج الـ ATS بتتجاهل المساحات دي.")

    return {
        "ats_score": ats_score,
        "detected_skills": formatted_skills,
        "feedback_en": feedback_en,
        "feedback_ar": feedback_ar
    }
