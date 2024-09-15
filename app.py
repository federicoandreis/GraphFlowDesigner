from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Project
from config import Config
import os
import json
from io import BytesIO
from openai import OpenAI
from urllib.parse import urlparse

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        login_user(user)
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user is not None:
            flash('Username already exists')
            return redirect(url_for('register'))
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('Access denied')
        return redirect(url_for('index'))
    users = User.query.all()
    projects = Project.query.all()
    return render_template('admin.html', users=users, projects=projects)

@app.route('/save_project', methods=['POST'])
@login_required
def save_project():
    data = request.json
    project = Project.query.filter_by(name=data['name'], user_id=current_user.id).first()
    if project:
        project.content = json.dumps(data['content'])
    else:
        project = Project(name=data['name'], content=json.dumps(data['content']), user_id=current_user.id)
        db.session.add(project)
    db.session.commit()
    return jsonify(success=True)

@app.route('/get_projects')
@login_required
def get_projects():
    projects = Project.query.filter_by(user_id=current_user.id).all()
    return jsonify([{'id': p.id, 'name': p.name, 'content': json.loads(p.content)} for p in projects])

@app.route('/get_node_suggestions')
def get_node_suggestions():
    with open('node_suggestions.json', 'r') as f:
        suggestions = json.load(f)
    return jsonify(suggestions)

@app.route('/export_graph', methods=['POST'])
@login_required
def export_graph():
    graph_data = request.json
    json_data = json.dumps(graph_data, indent=2)
    return send_file(BytesIO(json_data.encode()), mimetype='application/json', as_attachment=True, download_name='graph_export.json')

@app.route('/import_graph', methods=['POST'])
@login_required
def import_graph():
    if 'file' not in request.files:
        return jsonify(success=False, error='No file part')
    file = request.files['file']
    if file.filename == '':
        return jsonify(success=False, error='No selected file')
    if file:
        try:
            graph_data = json.load(file)
            return jsonify(success=True, content=graph_data)
        except json.JSONDecodeError:
            return jsonify(success=False, error='Invalid JSON file')

@app.route('/admin/generate_graph', methods=['POST'])
@login_required
def generate_graph():
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Access denied'})

    prompt = request.json.get('prompt') if request.json else None
    if not prompt:
        return jsonify({'success': False, 'error': 'No prompt provided'})

    try:
        # Use OpenAI GPT to generate graph data
        graph_data = generate_graph_data_with_gpt(prompt)
        return jsonify({'success': True, 'graph_data': graph_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def generate_graph_data_with_gpt(prompt):
    client = OpenAI(
        api_key=os.environ.get('OPENAI_API_KEY'),
        organization='org-SltZ4uEu1VAOxCnlY8qzWH3a'
    )
    
    # Prepare the prompt for GPT with the provided preamble
    gpt_prompt = f"""
    You are an AI assistant and expert scientist, tasked with creating a detailed Directed Acyclic Graph (DAG) that illustrates the causal mechanisms based on established scientific evidence. Your goal is to analyze the given prompt and generate a structured representation of the specific causal links described in the scientific literature.

Please follow these guidelines:
a
1. **Identify Key Concepts and Events:**
   - Extract specific factors, processes, and outcomes mentioned or implied in the prompt.
   - Use your domain knowledge to include relevant intermediate steps supported by scientific evidence.

2. **Determine Causal Relationships:**
   - Map out how each concept or event causally influences others.
   - Include biological, chemical, environmental, and behavioral mechanisms as appropriate.   

3. **Create a Detailed DAG Structure:**
   - Each node should represent a specific concept, factor, or event.
   - Each edge should represent a direct causal link from one node to another.
   - There can be edges between nodes that are not directly related to each other, but still contribute to the overall structure. This is a critical step to ensure a coherent and complete graph.

4. **Ensure Graph Acyclicity:**
   - The graph must be acyclic with no circular dependencies.

5. **Provide Clear Labels and Annotations:**
   - **Nodes:**
     - Include 'id', 'label', and 'title' for each node.
     - 'label' should be concise yet descriptive.
     - 'title' should provide a brief explanation or reference to scientific evidence (e.g., "Benzo[a]pyrene in tobacco smoke causes DNA adducts leading to mutations [Smith et al., 2020]").

6. **Cite Sources:**
   - When possible, reference scientific studies or reviews that support each causal link (use placeholder citations if necessary).

7. **Output Format:**
   - Return the result as a JSON object with two keys: 'nodes' and 'edges'.
   - **'nodes'**: A list of objects, each with 'id', 'label', and 'title'.
   - **'edges'**: A list of objects, each with 'from' and 'to' keys representing connections between nodes.

**Based on the following prompt, generate a detailed directed acyclic graph (DAG) structure:**

Prompt: {prompt}
"""

    # Call GPT-3.5-turbo API
    response = client.chat.completions.create(
        model='gpt-3.5-turbo-0125',
        messages=[
            {'role': 'system', 'content': 'You are an AI assistant tasked with creating a Directed Acyclic Graph (DAG) based on causal relationships.'},
            {'role': 'user', 'content': gpt_prompt}
        ],
        max_tokens=500,
        n=1,
        temperature=0.5,
    )

    # Parse the GPT response
    gpt_output = response.choices[0].message.content.strip()
    graph_structure = json.loads(gpt_output)

    return graph_structure

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
