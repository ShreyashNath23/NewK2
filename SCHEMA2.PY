import json
import networkx as nx
import requests
from pathlib import Path
from typing import Dict, List, Optional
from pyvis.network import Network
from dotenv import load_dotenv
import os

load_dotenv()  # This loads variables from the .env file into the environment
HF_API_KEY = os.getenv("HF_API_KEY")

class HFDescriber:
    def __init__(self, api_key: str, model: str = "google/flan-t5-base"):
        self.api_key = api_key
        self.model = model
        self.endpoint = f"https://api-inference.huggingface.co/models/{self.model}"

    def _build_prompt(self, name: str, dtype: str, context: str) -> str:
        example = (
            "Example:\n"
            "Column Name: customer_id\n"
            "Data Type: integer\n"
            "Description: A unique identifier assigned to each customer, used to track customer interactions and transactions.\n\n"
        )
        instruction = (
            "Generate a detailed and accurate technical database column description. "
            "Focus on the intended purpose and usage of the column in a business or analytics context. "
            "Avoid generic statements and ensure the description is specific to the column's function.\n\n"
        )
        prompt = (
            f"{instruction}"
            f"{example}"
            f"Column Name: {name}\n"
            f"Data Type: {dtype}\n"
            f"{context if context else ''}\n\n"
            f"Description:"
        )
        return prompt

    def generate_description(self, column_name: str, data_type: str, context: Optional[str] = None) -> str:
        prompt = self._build_prompt(column_name, data_type, context)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "inputs": prompt,
            "parameters": {"max_new_tokens": 100, "temperature": 0.7},
            "options": {"wait_for_model": True}
        }
        try:
            response = requests.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            if isinstance(result, list) and result and "generated_text" in result[0]:
                return result[0]["generated_text"].strip()
            else:
                print(f"Unexpected response format: {result}")
                return "Description unavailable"
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
            return "API Error"
        except Exception as e:
            print(f"Error: {str(e)}")
            return "Description generation failed"

class DBTUnifiedSchema:
    def __init__(self, hf_api_key: Optional[str] = None):
        self.graph = nx.DiGraph()
        self.projects = []
        self.ai_descriptions = {}
        self.describer = HFDescriber(hf_api_key) if hf_api_key else None

    def load_projects(self, project_paths: List[str]):
        for path in project_paths:
            try:
                manifest_path = Path(path) / "target/manifest.json"
                if not manifest_path.exists():
                    raise FileNotFoundError(f"Manifest not found at {manifest_path}")
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                project_name = Path(path).name
                models = {
                    nid: nd 
                    for nid, nd in manifest.get("nodes", {}).items() 
                    if nd.get("resource_type") == "model"
                }
                if not models:
                    continue
                for model in models.values():
                    model["unique_name"] = f"{project_name}.{model['name']}"
                    model["project"] = project_name
                self.projects.append({
                    "name": project_name,
                    "path": str(path),
                    "models": models
                })
            except Exception as e:
                print(f"Failed to load {path}: {str(e)}")
                continue

    def build_graph(self):
        if not self.projects:
            print("No projects loaded.")
            return
        for project in self.projects:
            for model_id, model in project["models"].items():
                self.graph.add_node(
                    model["unique_name"],
                    project=model["project"],
                    columns=model.get("columns", {}),
                    description=model.get("description", ""),
                    original_name=model["name"]
                )
                for parent_id in model.get("depends_on", {}).get("nodes", []):
                    parent_name = self._find_parent(parent_id)
                    if parent_name:
                        self.graph.add_edge(parent_name, model["unique_name"])

    def _find_parent(self, parent_id: str) -> Optional[str]:
        for project in self.projects:
            if parent_id in project["models"]:
                return project["models"][parent_id]["unique_name"]
        print(f"Parent not found: {parent_id}")
        return None

    def enhance_with_ai(self, context_strategy: str = "basic"):
        if not self.describer:
            print("AI disabled: No API key provided")
            return
        total_columns = sum(
            len(model.get("columns", {})) 
            for p in self.projects 
            for model in p["models"].values()
        )
        processed = 0
        for project in self.projects:
            for model_id, model in project["models"].items():
                model_name = model["unique_name"]
                self.ai_descriptions[model_name] = {}
                for col_name, col in model.get("columns", {}).items():
                    context = self._get_context(col, model, context_strategy)
                    ai_desc = self.describer.generate_description(
                        column_name=col_name,
                        data_type=col.get("data_type", "unknown"),
                        context=context
                    )
                    col["ai_description"] = ai_desc
                    self.ai_descriptions[model_name][col_name] = ai_desc
                    processed += 1
                    print(f"Progress: {processed}/{total_columns} columns", end="\r")
        print(f"\nGenerated descriptions for {processed} columns")

    def _get_context(self, column: Dict, model: Dict, strategy: str) -> str:
        context = []
        if strategy == "code":
            context.append(f"SQL snippet: {model.get('compiled_code', '')[:300]}...")
        context.append(f"Model: {model['name']} ({model['project']})")
        context.append(f"Relationships: {', '.join(model.get('depends_on', {}).get('nodes', []))}")
        return "\n".join(context)

    def export_schema(self, filename: str = "unified_schema.json"):
        if not self.graph.nodes:
            print("Nothing to export - empty graph")
            return
        output = {
            "meta": {"generated_with": "DBT Unified Schema Generator"},
            "nodes": [
                {"id": n, **data}
                for n, data in self.graph.nodes(data=True)
            ],
            "edges": [{"source": s, "target": t} for s, t in self.graph.edges],
            "ai_descriptions": self.ai_descriptions
        }
        try:
            with open(filename, "w") as f:
                json.dump(output, f, indent=2)
            print(f"Successfully exported to {filename}")
        except Exception as e:
            print(f"Export failed: {str(e)}")

    def visualize(self, filename: str = "lineage.html"):
        if not self.graph.nodes:
            print("Nothing to visualize - empty graph")
            return
        try:
            net = Network(
                directed=True,
                cdn_resources="in_line",
                height="800px",
                width="100%"
            )
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            for node, data in self.graph.nodes(data=True):
                net.add_node(
                    node,
                    label=data.get('project', 'Unknown') + "." + data.get('original_name', node),
                    title=f"Columns: {len(data.get('columns', {}))}\n{data.get('description', '')}",
                    size=25
                )
            for edge in self.graph.edges:
                net.add_edge(edge[0], edge[1])
            html_content = net.generate_html()
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"Visualization saved to {filename}")
        except Exception as e:
            print(f"Visualization failed: {str(e)}")

if __name__ == "__main__":
    BASE_PROJECTS_PATH = r"F:\dbt_projects"  
    project_dir = Path(BASE_PROJECTS_PATH)
    BASE_PROJECTS_PATH = r"F:\dbt_projects"
    project_dir = Path(BASE_PROJECTS_PATH)
    PROJECT_PATHS = [
        str(subdir) for subdir in project_dir.iterdir() 
        if subdir.is_dir() and (subdir / "target/manifest.json").exists()
    ]


    aggregator = DBTUnifiedSchema(hf_api_key=HF_API_KEY)
    aggregator.load_projects(PROJECT_PATHS)
    aggregator.build_graph()
    if aggregator.graph.nodes:
        aggregator.enhance_with_ai()
        aggregator.export_schema("enhanced_schema.json")
        aggregator.visualize("lineage.html")
    else:
        print("No data to process - check project loading")
