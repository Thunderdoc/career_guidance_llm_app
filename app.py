import streamlit as st

st.title("🎓 Career Guidance AI App (Mock Version)")
st.markdown("This mock app simulates career guidance suggestions based on your skills or resume.")

skills_input = st.text_area("Paste your skills, resume summary, or interests here:")

mock_response = """
1. **Software Developer** – Your programming and web development skills make you suitable for roles in full-stack or backend development.
2. **Data Analyst** – With knowledge of Python, Excel, and data visualization, you can work on data-driven decision making.
3. **Technical Writer** – Your communication and tech background fit well with documenting software, APIs, and guides.
4. **QA Engineer** – Your detail-oriented nature and coding skills are perfect for testing and quality assurance roles.
5. **Product Support Specialist** – Strong communication and tech awareness are a great match for user support and troubleshooting.
"""

if st.button("Suggest Career Paths"):
    if not skills_input.strip():
        st.warning("Please enter some skills or resume content.")
    else:
        st.success("Here are some mock career suggestions:")
        st.markdown(mock_response)
