# app.py
import streamlit as st
import sqlite3
import pandas as pd
from io import BytesIO
from datetime import datetime
import os

# -------------------------
# Database helpers
# -------------------------
DB_PATH = "data/results.db"
os.makedirs("data", exist_ok=True)

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # students table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        student_id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll TEXT UNIQUE,
        name TEXT,
        program TEXT
    )
    """)
    # subjects table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        title TEXT,
        credits REAL
    )
    """)
    # marks table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS marks (
        mark_id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        subject_id INTEGER,
        marks REAL,
        max_marks REAL,
        FOREIGN KEY(student_id) REFERENCES students(student_id),
        FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
    )
    """)
    conn.commit()
    conn.close()

init_db()

# -------------------------
# Business logic
# -------------------------
def grade_from_percent(p):
    # typical scale - adjust to your institute
    if p >= 90: return ("A+", 10.0)
    if p >= 80: return ("A", 9.0)
    if p >= 70: return ("B+", 8.0)
    if p >= 60: return ("B", 7.0)
    if p >= 50: return ("C", 6.0)
    if p >= 40: return ("D", 5.0)
    return ("F", 0.0)

def compute_student_report(student_id):
    conn = get_conn()
    q = """
    SELECT s.student_id, s.roll, s.name, sub.code, sub.title, sub.credits, m.marks, m.max_marks
    FROM students s
    JOIN marks m ON s.student_id = m.student_id
    JOIN subjects sub ON m.subject_id = sub.subject_id
    WHERE s.student_id = ?
    """
    df = pd.read_sql_query(q, conn, params=(student_id,))
    conn.close()
    if df.empty:
        return None

    # compute percent, grade, grade_points
    df['percent'] = (df['marks'] / df['max_marks']) * 100
    df[['grade', 'grade_point']] = df['percent'].apply(
        lambda p: pd.Series(grade_from_percent(p))
    )
    # credit*grade_point
    df['credit_gp'] = df['credits'] * df['grade_point']

    total_credits = df['credits'].sum()
    total_credit_gp = df['credit_gp'].sum()
    cgpa = (total_credit_gp / total_credits) if total_credits > 0 else 0.0

    summary = {
        "roll": df.iloc[0]['roll'],
        "name": df.iloc[0]['name'],
        "total_credits": float(total_credits),
        "total_credit_gp": float(total_credit_gp),
        "cgpa": round(cgpa, 2),
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }
    return df, summary

# -------------------------
# Data operations
# -------------------------
def add_student(roll, name, program=""):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO students (roll, name, program) VALUES (?, ?, ?)", (roll, name, program))
        conn.commit()
        st.success("Student added")
    except sqlite3.IntegrityError:
        st.warning("Student with this roll already exists.")
    finally:
        conn.close()

def add_subject(code, title, credits):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO subjects (code, title, credits) VALUES (?, ?, ?)", (code, title, float(credits)))
        conn.commit()
        st.success("Subject added")
    except sqlite3.IntegrityError:
        st.warning("Subject with this code already exists.")
    finally:
        conn.close()

def add_marks(roll, subject_code, marks, max_marks=100):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT student_id FROM students WHERE roll = ?", (roll,))
        s = cur.fetchone()
        if not s:
            st.error("Student roll not found.")
            return
        student_id = s[0]
        cur.execute("SELECT subject_id FROM subjects WHERE code = ?", (subject_code,))
        sub = cur.fetchone()
        if not sub:
            st.error("Subject code not found.")
            return
        subject_id = sub[0]
        # upsert: if a mark exists for this student & subject, replace it
        cur.execute("""
        SELECT mark_id FROM marks WHERE student_id = ? AND subject_id = ?
        """, (student_id, subject_id))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE marks SET marks=?, max_marks=? WHERE mark_id=?", (float(marks), float(max_marks), existing[0]))
        else:
            cur.execute("INSERT INTO marks (student_id, subject_id, marks, max_marks) VALUES (?, ?, ?, ?)",
                        (student_id, subject_id, float(marks), float(max_marks)))
        conn.commit()
        st.success("Marks saved")
    finally:
        conn.close()

def get_all_students_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT student_id, roll, name, program FROM students ORDER BY roll", conn)
    conn.close()
    return df

def get_all_subjects_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT subject_id, code, title, credits FROM subjects ORDER BY code", conn)
    conn.close()
    return df

def export_df_to_excel_bytes(dfs: dict):
    with BytesIO() as b:
        with pd.ExcelWriter(b, engine="openpyxl") as writer:
            for sheet_name, df in dfs.items():
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        return b.getvalue()

# -------------------------
# Streamlit UI
# -------------------------
st.set_page_config(page_title="Result Processor", layout="wide")

st.title("📘 Digital Result Processor")
st.markdown("""
A simple Streamlit app to add students, subjects, and marks; compute grades & CGPA; and export reports.
""")

menu = st.sidebar.selectbox("Go to", ["Dashboard", "Add Data", "Enter Marks", "Student Report", "Export", "Admin"])

if menu == "Dashboard":
    st.header("Class Summary")
    students = get_all_students_df()
    subjects = get_all_subjects_df()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Students")
        st.write(f"Total students: {len(students)}")
        st.dataframe(students)
    with col2:
        st.subheader("Subjects")
        st.write(f"Total subjects: {len(subjects)}")
        st.dataframe(subjects)

    # quick class CGPA table
    if st.button("Compute CGPA for all students"):
        out = []
        for sid in students['student_id'].tolist():
            result = compute_student_report(sid)
            if result:
                df, summ = result
                out.append({
                    "roll": summ['roll'],
                    "name": summ['name'],
                    "cgpa": summ['cgpa'],
                    "total_credits": summ['total_credits']
                })
        if out:
            st.dataframe(pd.DataFrame(out).sort_values(["cgpa"], ascending=False))
        else:
            st.info("No marks present yet.")

elif menu == "Add Data":
    st.header("Add Students & Subjects")
    with st.form("student_form"):
        st.subheader("Add student")
        roll = st.text_input("Roll (unique)", value="")
        name = st.text_input("Name")
        program = st.text_input("Program / Course (optional)")
        submitted = st.form_submit_button("Add student")
        if submitted:
            if roll.strip() == "" or name.strip() == "":
                st.error("Fill roll and name.")
            else:
                add_student(roll.strip(), name.strip(), program.strip())

    st.markdown("---")
    with st.form("subject_form"):
        st.subheader("Add subject")
        code = st.text_input("Subject code (unique)", value="", key="scode")
        title = st.text_input("Title", key="stitle")
        credits = st.number_input("Credits", min_value=0.0, value=3.0, step=0.5, key="scredit")
        submitted2 = st.form_submit_button("Add subject")
        if submitted2:
            if code.strip() == "" or title.strip() == "":
                st.error("Fill code and title.")
            else:
                add_subject(code.strip(), title.strip(), float(credits))

elif menu == "Enter Marks":
    st.header("Enter / Update Marks")
    students = get_all_students_df()
    subs = get_all_subjects_df()
    if students.empty or subs.empty:
        st.info("You need to add at least one student and one subject first.")
    else:
        with st.form("marks_form"):
            roll = st.selectbox("Student (by roll)", students['roll'].tolist())
            subject_code = st.selectbox("Subject code", subs['code'].tolist())
            marks = st.number_input("Marks obtained", min_value=0.0, value=0.0)
            max_marks = st.number_input("Max marks (for percent)", min_value=1.0, value=100.0)
            submitted3 = st.form_submit_button("Save marks")
            if submitted3:
                add_marks(roll, subject_code, marks, max_marks)

elif menu == "Student Report":
    st.header("Generate Student Report")
    students = get_all_students_df()
    if students.empty:
        st.info("No students yet.")
    else:
        roll_selected = st.selectbox("Choose student", students['roll'].tolist())
        sid = int(students[students['roll']==roll_selected]['student_id'].iloc[0])
        res = compute_student_report(sid)
        if not res:
            st.warning("No marks recorded for this student yet.")
        else:
            df, summary = res
            st.subheader(f"{summary['name']} — {summary['roll']}")
            st.metric("CGPA", summary['cgpa'])
            st.write("Detailed marks / grades")
            display_df = df[['code','title','credits','marks','max_marks','percent','grade','grade_point']]
            st.dataframe(display_df.style.format({"percent":"{:.2f}","grade_point":"{:.2f}"}), height=300)

            # Download CSV/Excel
            csv_bytes = display_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download CSV", csv_bytes, file_name=f"report_{summary['roll']}.csv", mime="text/csv")

            if st.button("Export Excel for this student"):
                bytes_xl = export_df_to_excel_bytes({"report": display_df})
                st.download_button("Download Excel", bytes_xl, file_name=f"report_{summary['roll']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif menu == "Export":
    st.header("Export All Data")
    students = get_all_students_df()
    subjects = get_all_subjects_df()

    conn = get_conn()
    marks_df = pd.read_sql_query("""
    SELECT s.roll, s.name, sub.code AS subject_code, sub.title AS subject_title, sub.credits,
           m.marks, m.max_marks
    FROM marks m
    JOIN students s ON m.student_id = s.student_id
    JOIN subjects sub ON m.subject_id = sub.subject_id
    ORDER BY s.roll
    """, conn)
    conn.close()

    st.write("Students")
    st.dataframe(students)
    st.write("Subjects")
    st.dataframe(subjects)
    st.write("Marks")
    st.dataframe(marks_df)

    if st.button("Export All to Excel"):
        bytes_xl = export_df_to_excel_bytes({
            "students": students,
            "subjects": subjects,
            "marks": marks_df
        })
        st.download_button("Download Excel", bytes_xl, file_name="all_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif menu == "Admin":
    st.header("Admin / DB Tools")
    if st.button("Reset ALL data (drop tables)"):
        if st.confirm("Are you sure? This will erase all data."):
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("DROP TABLE IF EXISTS marks")
            cur.execute("DROP TABLE IF EXISTS subjects")
            cur.execute("DROP TABLE IF EXISTS students")
            conn.commit()
            conn.close()
            init_db()
            st.success("Database reset.")
    st.markdown("Use this to backup the DB file (`data/results.db`) before destructive operations.")

# footer
st.sidebar.markdown("---")
st.sidebar.write("Built with ❤️ using Streamlit")
