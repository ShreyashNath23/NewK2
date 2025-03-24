import streamlit as st
import json
import networkx as nx
from pyvis.network import Network
import tempfile
import os
import pandas as pd

st.set_page_config(page_title="Intuitive DBT UI", layout="wide")
custom_css = """
<style>
    .model-card {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin-bottom: 10px;
    }
    .model-card h4 {
        margin-bottom: 5px;
        color: #333;
    }
    .model-card p {
        margin: 5px 0;
        color: #555;
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

st.title("Intuitive DBT UI")

st.sidebar.header("Upload Unified Schema File")
uploaded_file = st.sidebar.file_uploader(
    "Upload enhanced_schema.json",
    type=["json"],
    accept_multiple_files=False
)

if uploaded_file:
    try:
        unified_schema = json.load(uploaded_file)
    except Exception as e:
        st.error(f"Error processing file: {e}")
        st.stop()
else:
    st.info("Please upload your enhanced unified schema file (enhanced_schema.json).")
    st.stop()

nodes = unified_schema.get("nodes", [])
edges = unified_schema.get("edges", [])
ai_desc = unified_schema.get("ai_descriptions", {})

st.sidebar.header("Filters & Search")
projects = sorted(list({node.get("project", "Unknown") for node in nodes}))
selected_projects = st.sidebar.multiselect("Select Projects", options=projects, default=projects)
search_text = st.sidebar.text_input("Search Models (by ID or name)", "")

def filter_nodes(nodes, selected_projects, search):
    filtered = [node for node in nodes if node.get("project", "Unknown") in selected_projects]
    if search:
        search_lower = search.lower()
        filtered = [
            node for node in filtered 
            if search_lower in node.get("id", "").lower() or search_lower in node.get("original_name", "").lower()
        ]
    return filtered

filtered_nodes = filter_nodes(nodes, selected_projects, search_text)

tabs = st.tabs(["Models Overview", "Model Details", "Lineage Graph"])

with tabs[0]:
    st.header("Models Overview")
    if not filtered_nodes:
        st.write("No models match the current filters.")
    else:
        for node in filtered_nodes:
            model_id = node.get("id", "N/A")
            model_display_name = node.get("original_name", model_id.split(".")[-1]).replace("_", " ").upper()
            columns = node.get("columns", {})
            column_data = [
                (col_name, col.get("data_type", "Unknown"), col.get("ai_description") or "No description available.")
                for col_name, col in columns.items()
            ]
            st.markdown(f"""
                <div class="model-card">
                    <h4 style="text-align: center;">{model_display_name}</h4>
                </div>
            """, unsafe_allow_html=True)
            if column_data:
                df_columns = pd.DataFrame(column_data, columns=["Column Name", "Data Type", "Description"])
                st.dataframe(df_columns, hide_index=True)
            else:
                st.write("No column information available.")

with tabs[1]:
    st.header("Model Details")
    if not filtered_nodes:
        st.write("No models available. Adjust your filters.")
    else:
        model_options = {node["id"]: node for node in filtered_nodes}
        custom_cursor_css = """
        <style>
            div[data-baseweb="select"], div[data-baseweb="select"] * {
                cursor: pointer !important;
            }
        </style>
        """
        st.markdown(custom_cursor_css, unsafe_allow_html=True)
        selected_model_id = st.selectbox("Select a model for details", options=list(model_options.keys()))
        selected_model = model_options[selected_model_id]
        st.subheader(f"Model: {selected_model.get('original_name', selected_model_id)}")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Project:** {selected_model.get('project', 'N/A')}")
            st.markdown(f"**ID:** {selected_model.get('id', 'N/A')}")
        with col2:
            st.markdown(f"**Description:** {selected_model.get('description', 'N/A')}")
        st.subheader("Columns & Data Types")
        if "columns" in selected_model and selected_model["columns"]:
            column_data = [(col_name, col.get("data_type", "unknown")) for col_name, col in selected_model["columns"].items()]
            df_columns = pd.DataFrame(column_data, columns=["Column Name", "Data Type"])
            st.markdown("""
            <div style="overflow-x: auto;">
            """, unsafe_allow_html=True)
            st.dataframe(df_columns, hide_index=True)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.write("No column information available.")
        st.subheader("Dependencies")
        deps = selected_model.get("depends_on", {}).get("nodes", [])
        if deps:
            st.dataframe(pd.DataFrame(deps, columns=["Depends On"]), hide_index=True)
        else:
            st.write("No dependencies available.")

with tabs[2]:
    rounded_box_css = """
    <style>
        .lineage-container {
            background-color: #ffffff;
            border-radius: 15px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
            padding: 20px;
            margin-top: -20px;
            overflow: hidden;
        }
        iframe {
            border-radius: 15px;
            overflow: hidden;
        }
        h2 {
            margin-top: 0px !important;
            padding-top: 0px !important;
        }
    </style>
    """
    st.markdown(rounded_box_css, unsafe_allow_html=True)
    st.markdown('<div class="lineage-container">', unsafe_allow_html=True)
    st.markdown("<h2>Lineage Graph</h2>", unsafe_allow_html=True)
    filtered_ids = {node["id"] for node in filtered_nodes}
    graph = nx.DiGraph()
    project_colors = {}
    colors = ["#FF5733", "#33FF57", "#3357FF", "#FF33A8", "#A833FF", "#33FFF5"]
    project_list = list({node["project"] for node in filtered_nodes})
    for i, project in enumerate(project_list):
        project_colors[project] = colors[i % len(colors)]
    for node in filtered_nodes:
        project = node.get("project", "Unknown")
        graph.add_node(
            node["id"],
            label=node.get("original_name", node["id"]).replace("_", " ").upper(),
            color=project_colors.get(project, "#AAAAAA"),
            size=len(node.get("depends_on", {}).get("nodes", [])) * 10 + 10
        )
    for edge in unified_schema.get("edges", []):
        if edge["source"] in filtered_ids and edge["target"] in filtered_ids:
            graph.add_edge(edge["source"], edge["target"])
    net = Network(height="600px", width="100%", directed=True, notebook=False)
    net.barnes_hut(gravity=-5000, central_gravity=0.3, spring_length=180, damping=0.85)
    net.set_options('''
        var options = {
            "nodes": {
                "borderWidth": 2,
                "shape": "circle",
                "color": {"border": "#222222"},
                "font": {"size": 16, "bold": true}
            },
            "edges": {
                "color": {"color": "#888888"},
                "arrows": {"to": {"enabled": true, "scaleFactor": 1.2}},
                "smooth": {"enabled": true, "type": "continuous"}
            },
            "physics": {
                "barnesHut": {
                    "gravitationalConstant": -5000,
                    "springLength": 150,
                    "damping": 0.85
                },
                "minVelocity": 0.75
            }
        }
    ''')
    for n, attrs in graph.nodes(data=True):
        net.add_node(n, label=attrs.get("label", n), color=attrs["color"], size=attrs["size"])
    for s, t in graph.edges():
        net.add_edge(s, t)
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.html', encoding="utf-8") as tmp_file:
        net.write_html(tmp_file.name)
        tmp_filename = tmp_file.name
    with open(tmp_filename, 'r', encoding='utf-8') as f:
        html_content = f.read()
    st.components.v1.html(html_content, height=600, scrolling=True)
    st.markdown('</div>', unsafe_allow_html=True)
    os.remove(tmp_filename)
