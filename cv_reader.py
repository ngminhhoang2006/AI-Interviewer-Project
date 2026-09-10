import pymupdf
import re
import json
from pathlib import Path


def find_pdf(pdf_name):
    """Search recursively for the PDF starting from the script directory."""

    script_dir = Path(__file__).resolve().parent

    matches = list(script_dir.rglob(pdf_name))

    if not matches:
        return None

    return matches[0]


def extract_text(pdf_path):
    """Extract all text from a PDF."""

    document = pymupdf.open(pdf_path)

    text = ""

    for page in document:
        text += page.get_text() + "\n"

    document.close()

    return text


def extract_applicant_info(text):
    """Extract structured applicant information from CV text."""

    info = {
        "name": None,
        "email": None,
        "phone": None,
        "address": None,
        "age": None,
        "education": [],
        "experience": [],
        "projects": [],
        "skills": [],
        "certifications": [],
        "awards": []
    }

    # --------------------------------------------------
    # EMAIL
    # --------------------------------------------------

    email_pattern = r"""
        (?:✉|📧|email|e-mail|mail)\s*:?\s*
        ([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})
        |
        ([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})
    """

    email_match = re.search(
        email_pattern,
        text,
        re.IGNORECASE | re.VERBOSE
    )

    if email_match:
        info["email"] = next(
            group for group in email_match.groups() if group
        )

    # --------------------------------------------------
    # PHONE
    # --------------------------------------------------

    phone_pattern = r"""
        (?:
            📞|☎|📱|
            phone|tel|telephone|mobile|contact|điện\s*thoại|sđt|liên\s*hệ
        )
        \s*:?\s*
        (\+?\d[\d\s().-]{7,}\d)
        |
        (?<!\d)
        (\+?\d{9,15})
        (?!\d)
    """

    phone_match = re.search(
        phone_pattern,
        text,
        re.IGNORECASE | re.VERBOSE
    )

    if phone_match:
        phone = next(
            group for group in phone_match.groups() if group
        )

        # Clean unnecessary spaces
        info["phone"] = phone.strip()

    # --------------------------------------------------
    # ADDRESS
    # --------------------------------------------------

    address_pattern = r"""
        (?:
            |📍|
            address|location|địa\s+chỉ|nơi\s+ở|chỗ\s+ở
        )
        \s*:?\s*
        ([^\n]+)
    """

    address_match = re.search(
        address_pattern,
        text,
        re.IGNORECASE | re.VERBOSE
    )

    if address_match:
        info["address"] = address_match.group(1).strip()

    # --------------------------------------------------
    # AGE
    # --------------------------------------------------

    age_pattern = r"""
        (?:
            age|tuổi
            |
            (\d{1,3})\s*(?:years?\s*old|tuổi)
        )
        \s*:?\s*
        (\d{1,3})?
    """

    age_match = re.search(
        age_pattern,
        text,
        re.IGNORECASE | re.VERBOSE
    )

    if age_match:
        age = age_match.group(2) or age_match.group(1)

        if age:
            info["age"] = int(age)

    # --------------------------------------------------
    # NAME
    # --------------------------------------------------

    name_patterns = [
        r"(?:full\s*name|name|họ\s*và\s*tên|họ\s*tên|tên)\s*:?\s*([^\n]+)"
    ]

    for pattern in name_patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            info["name"] = match.group(1).strip()
            break

    # If no explicit name label exists,
    # assume the first non-empty line is the name.
    if not info["name"]:
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if lines:
            info["name"] = lines[0]

    # --------------------------------------------------
    # SECTION EXTRACTION
    # --------------------------------------------------

    sections = {
        "education": [
            "EDUCATION",
            "EDUCATIONAL BACKGROUND",
            "ACADEMIC BACKGROUND",
            "HỌC VẤN",
            "TRÌNH ĐỘ HỌC VẤN",
            "GIÁO DỤC"
        ],

        "experience": [
            "EXPERIENCE",
            "WORK EXPERIENCE",
            "EMPLOYMENT",
            "EMPLOYMENT HISTORY",
            "KINH NGHIỆM",
            "KINH NGHIỆM LÀM VIỆC",
            "LỊCH SỬ LÀM VIỆC"
        ],

        "projects": [
            "PROJECTS",
            "PROJECT EXPERIENCE",
            "DỰ ÁN",
            "DỰ ÁN ĐÃ THỰC HIỆN",
            "DỰ ÁN CAO CẤP"
        ],

        "skills": [
            "SKILLS",
            "TECHNICAL SKILLS",
            "CORE SKILLS",
            "KỸ NĂNG",
            "KỸ NĂNG CHUYÊN MÔN"
        ],

        "certifications": [
            "CERTIFICATIONS",
            "CERTIFICATES",
            "CHỨNG CHỈ",
            "BẰNG CẤP"
        ],

        "awards": [
            "HONORS & AWARDS",
            "HONORS AND AWARDS",
            "AWARDS",
            "ACHIEVEMENTS",
            "GIẢI THƯỞNG",
            "THÀNH TÍCH",
            "DANH HIỆU"
        ]
    }

    # Build a regex containing all section names
    all_sections = []

    for section_names in sections.values():
        all_sections.extend(section_names)

    section_regex = "|".join(
        re.escape(section)
        for section in all_sections
    )

    # Find every section heading
    matches = list(
        re.finditer(
            rf"(?im)^\s*(?:{section_regex})\s*$",
            text
        )
    )

    for i, match in enumerate(matches):

        heading = match.group().strip().upper()

        start = match.end()

        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        section_text = text[start:end].strip()

        # Determine which category this belongs to
        for category, names in sections.items():

            if heading in names:

                lines = [
                    line.strip()
                    for line in section_text.splitlines()
                    if line.strip()
                ]

                info[category] = lines

                break

    return info


def main():

    # --------------------------------------------------
    # ASK FOR PDF
    # --------------------------------------------------
    pdf_name = input("Enter the CV filename / Nhập tên file CV: ").strip()

    # Automatically append .pdf extension if user omitted it
    if not pdf_name.lower().endswith(".pdf"):
        pdf_name += ".pdf"

    pdf_path = find_pdf(pdf_name)

    if pdf_path is None:
        print(f"Could not find '{pdf_name}' / Không tìm thấy file '{pdf_name}'.")
        return

    print(f"\nFound PDF / Đã tìm thấy PDF:")
    print(pdf_path)

    # --------------------------------------------------
    # EXTRACT TEXT
    # --------------------------------------------------

    text = extract_text(pdf_path)

    # --------------------------------------------------
    # PARSE CV
    # --------------------------------------------------

    applicant = extract_applicant_info(text)

    # --------------------------------------------------
    # CREATE DIRECTORY & JSON OUTPUT PATH
    # --------------------------------------------------

    # Fallback to default folder name if name extraction fails
    raw_name = applicant.get("name") or "Unknown_Applicant"

    # Sanitize name to avoid invalid directory characters (\ / : * ? " < > |)
    safe_name = re.sub(r'[\\/*?:"<>|]', "", raw_name).strip()

    # Create the folder named after the applicant relative to script_dir
    output_dir = pdf_path.parent / safe_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Path to save the JSON inside the applicant's folder
    output_path = output_dir / f"{safe_name}.json"

    # --------------------------------------------------
    # SAVE JSON
    # --------------------------------------------------

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as json_file:

        json.dump(
            applicant,
            json_file,
            indent=4,
            ensure_ascii=False
        )

    print("\nCV successfully parsed! (Thành công!)")

    print(f"JSON saved to:")
    print(output_path)

    # Also display the result
    print("\nExtracted information:")
    print(
        json.dumps(
            applicant,
            indent=4,
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()