from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import os
import sys
import socket
import json
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, portrait
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend
from reportlab.pdfgen import canvas
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import text

# Determine if running as a compiled executable (PyInstaller)
if getattr(sys, 'frozen', False):
    # If frozen, templates are in the temp folder (_MEIPASS)
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    app = Flask(__name__, template_folder=template_folder)
    # Database should be stored next to the executable
    basedir = os.path.dirname(sys.executable)

    # Redirect stdout and stderr to null to prevent crashes in --noconsole mode
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')
else:
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'gear.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'

# Upload Configuration
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False) # e.g., Backpack, Shelter
    weight = db.Column(db.Float, default=0.0) # In grams or oz
    cost = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Kit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    total_weight = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    # For simplicity in this example, we store the list of item IDs as a string
    # In a production app, you would use a Many-to-Many relationship table.
    item_ids = db.Column(db.String(500)) 
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    currency_symbol = db.Column(db.String(5), default='£')
    weight_unit = db.Column(db.String(10), default='metric') # 'metric' or 'imperial'
    username = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

# Define our fixed categories
CATEGORIES = [
    "Backpack", "Chestpack", "Shelter", 
    "Sleep System", "Cook System", "Clothing", 
    "Water", "Lighting", "Comfort", "Commodities"
]

# --- Helpers & Context Processors ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_settings():
    """Make settings available to all templates."""
    if not current_user.is_authenticated:
        return dict(settings=None)
    settings = Settings.query.filter_by(user_id=current_user.id).first()
    if not settings:
        settings = Settings(currency_symbol='£', weight_unit='metric', user_id=current_user.id)
        db.session.add(settings)
        db.session.commit()
    return dict(settings=settings)

@app.template_filter('format_weight')
def format_weight_filter(weight_g):
    if not current_user.is_authenticated:
        return f"{weight_g/1000:.2f} kg"
    settings = Settings.query.filter_by(user_id=current_user.id).first()
    if settings and settings.weight_unit == 'imperial':
        lbs = weight_g * 0.00220462
        oz = weight_g * 0.035274
        return f"{lbs:.2f} lbs ({oz:.1f} oz)"
    kg = weight_g / 1000
    return f"{kg:.2f} kg ({int(weight_g)} g)"

# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error="Username already exists")
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        seed_database(new_user.id)
        login_user(new_user)
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    # Fetch all items to populate dropdowns
    all_items = Item.query.filter_by(user_id=current_user.id).all()
    saved_kits = Kit.query.filter_by(user_id=current_user.id).all()
    
    # Organize items by category for the frontend
    items_by_cat = {cat: [] for cat in CATEGORIES}
    for item in all_items:
        if item.category in items_by_cat:
            items_by_cat[item.category].append(item)
            
    return render_template('index.html', categories=CATEGORIES, items_by_cat=items_by_cat, kits=saved_kits)

@app.route('/add_item', methods=['POST'])
@login_required
def add_item():
    name = request.form.get('name')
    category = request.form.get('category')
    weight = request.form.get('weight')
    cost = request.form.get('cost')
    notes = request.form.get('notes')
    
    image_filename = None
    file = request.files.get('image')
    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_filename = filename

    new_item = Item(name=name, category=category, weight=weight, cost=cost, notes=notes, image_filename=image_filename, user_id=current_user.id)
    db.session.add(new_item)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/edit_item/<int:id>', methods=['POST'])
@login_required
def edit_item(id):
    item = Item.query.get_or_404(id)
    if item.user_id != current_user.id: return redirect(url_for('index'))
    item.name = request.form.get('name')
    item.category = request.form.get('category')
    item.weight = request.form.get('weight')
    item.cost = request.form.get('cost')
    item.notes = request.form.get('notes')
    
    file = request.files.get('image')
    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        item.image_filename = filename
    
    db.session.commit()
    return redirect(request.referrer or url_for('inventory'))

@app.route('/edit_kit/<int:kit_id>')
@login_required
def edit_kit(kit_id):
    kit = Kit.query.get_or_404(kit_id)
    if kit.user_id != current_user.id: return redirect(url_for('index'))
    # Parse IDs
    item_ids = [int(i) for i in kit.item_ids.split(',') if i]
    items_in_db = Item.query.filter(Item.id.in_(item_ids)).all()
    items_map = {item.id: item for item in items_in_db}
    
    # Reconstruct list to preserve order (though grouping by cat will lose specific order within cat, which is acceptable here)
    kit_items = [items_map[i_id] for i_id in item_ids if i_id in items_map]
    
    # Group items by category for the frontend template
    edit_kit_items_by_cat = {cat: [] for cat in CATEGORIES}
    for item in kit_items:
        if item.category in edit_kit_items_by_cat:
            edit_kit_items_by_cat[item.category].append(item)

    # Standard fetch for dropdowns
    all_items = Item.query.filter_by(user_id=current_user.id).all()
    saved_kits = Kit.query.filter_by(user_id=current_user.id).all()
    items_by_cat = {cat: [] for cat in CATEGORIES}
    for item in all_items:
        if item.category in items_by_cat:
            items_by_cat[item.category].append(item)
            
    return render_template('index.html', 
                           categories=CATEGORIES, 
                           items_by_cat=items_by_cat, 
                           kits=saved_kits,
                           edit_kit=kit,
                           edit_kit_items_by_cat=edit_kit_items_by_cat)

@app.route('/update_kit/<int:kit_id>', methods=['POST'])
@login_required
def update_kit(kit_id):
    kit = Kit.query.get_or_404(kit_id)
    if kit.user_id != current_user.id: return redirect(url_for('index'))
    kit.name = request.form.get('kit_name')
    kit.notes = request.form.get('kit_notes')
    
    raw_ids = request.form.getlist('selected_items')
    selected_ids = [x for x in raw_ids if x != '0']
    
    items = Item.query.filter(Item.id.in_(selected_ids)).all()
    kit.total_weight = sum(i.weight for i in items)
    kit.total_cost = sum(i.cost for i in items)
    kit.item_ids = ",".join(selected_ids)
    
    db.session.commit()
    return redirect(url_for('view_kit', kit_id=kit.id))

@app.route('/delete_item/<int:id>')
@login_required
def delete_item(id):
    item = Item.query.get_or_404(id)
    if item.user_id != current_user.id: return redirect(url_for('index'))
    db.session.delete(item)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/save_kit', methods=['POST'])
@login_required
def save_kit():
    kit_name = request.form.get('kit_name')
    kit_notes = request.form.get('kit_notes')
    # Get the list of selected item IDs from the form
    raw_ids = request.form.getlist('selected_items')
    selected_ids = [x for x in raw_ids if x != '0']
    
    # Calculate totals on server side for safety
    items = Item.query.filter(Item.id.in_(selected_ids)).all()
    total_weight = sum(i.weight for i in items)
    total_cost = sum(i.cost for i in items)
    
    # Join IDs to store as string (e.g., "1,4,5")
    ids_str = ",".join(selected_ids)
    
    new_kit = Kit(name=kit_name, total_weight=total_weight, total_cost=total_cost, item_ids=ids_str, notes=kit_notes, user_id=current_user.id)
    db.session.add(new_kit)
    db.session.commit()
    
    return redirect(url_for('index'))

@app.route('/kit/<int:kit_id>')
@login_required
def view_kit(kit_id):
    kit = Kit.query.get_or_404(kit_id)
    if kit.user_id != current_user.id: return redirect(url_for('index'))
    # Parse IDs
    item_ids = [int(i) for i in kit.item_ids.split(',') if i]
    
    # Fetch items and map them for easy lookup
    items_in_db = Item.query.filter(Item.id.in_(item_ids)).all()
    items_map = {item.id: item for item in items_in_db}
    
    # Reconstruct list to preserve order and duplicates
    kit_items = [items_map[i_id] for i_id in item_ids if i_id in items_map]
            
    return render_template('kit_details.html', kit=kit, items=kit_items)

@app.route('/inventory')
@login_required
def inventory():
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.category, Item.name).all()
    return render_template('inventory.html', items=items, categories=CATEGORIES)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# API Endpoint for JavaScript to fetch item details instantly
@app.route('/api/item/<int:id>')
@login_required
def get_item_details(id):
    item = Item.query.get_or_404(id)
    if item.user_id != current_user.id: return jsonify({})
    return jsonify({
        'weight': item.weight,
        'cost': item.cost,
        'notes': item.notes
    })

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    settings = Settings.query.filter_by(user_id=current_user.id).first()
    if request.method == 'POST':
        settings.currency_symbol = request.form.get('currency_symbol')
        settings.weight_unit = request.form.get('weight_unit')
        settings.username = request.form.get('username')
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('settings.html', settings=settings)

@app.route('/backup/download')
@login_required
def download_backup():
    """Export database to JSON."""
    items = Item.query.filter_by(user_id=current_user.id).all()
    kits = Kit.query.filter_by(user_id=current_user.id).all()
    
    data = {
        "items": [{
            "name": i.name, "category": i.category, 
            "weight": i.weight, "cost": i.cost, "notes": i.notes
        } for i in items],
        "kits": [{
            "name": k.name, "total_weight": k.total_weight, 
            "total_cost": k.total_cost, "item_ids": k.item_ids
        } for k in kits]
    }
    
    # Create in-memory file
    mem = io.BytesIO()
    mem.write(json.dumps(data, indent=4).encode('utf-8'))
    mem.seek(0)
    
    return send_file(
        mem, 
        as_attachment=True, 
        download_name='hiker_app_backup.json', 
        mimetype='application/json'
    )

@app.route('/backup/upload', methods=['POST'])
@login_required
def upload_backup():
    """Import database from JSON."""
    if 'backup_file' not in request.files:
        return redirect(url_for('settings'))
        
    file = request.files['backup_file']
    if file.filename == '':
        return redirect(url_for('settings'))

    try:
        data = json.load(file)
        
        # Clear existing data
        db.session.query(Item).filter_by(user_id=current_user.id).delete()
        db.session.query(Kit).filter_by(user_id=current_user.id).delete()
        
        # Import Items
        for i in data.get('items', []):
            db.session.add(Item(name=i['name'], category=i['category'], weight=i['weight'], cost=i['cost'], notes=i['notes'], user_id=current_user.id))
            
        # Import Kits (Note: item_ids might be invalid if IDs shift, but we keep raw string)
        for k in data.get('kits', []):
            db.session.add(Kit(name=k['name'], total_weight=k['total_weight'], total_cost=k['total_cost'], item_ids=k['item_ids'], user_id=current_user.id))
            
        db.session.commit()
    except Exception as e:
        print(f"Error importing backup: {e}")
        
    return redirect(url_for('settings'))

@app.route('/kit/<int:kit_id>/export_json')
@login_required
def export_kit_json(kit_id):
    """Export a single kit and its items to JSON."""
    kit = Kit.query.get_or_404(kit_id)
    if kit.user_id != current_user.id: return redirect(url_for('index'))
    # Parse IDs
    item_ids = [int(i) for i in kit.item_ids.split(',') if i]
    items_in_db = Item.query.filter(Item.id.in_(item_ids)).all()
    items_map = {item.id: item for item in items_in_db}
    kit_items = [items_map[i_id] for i_id in item_ids if i_id in items_map]

    data = {
        "name": kit.name,
        "notes": kit.notes,
        "items": [{
            "name": i.name, "category": i.category, 
            "weight": i.weight, "cost": i.cost, 
            "notes": i.notes, "image_filename": i.image_filename
        } for i in kit_items]
    }
    
    mem = io.BytesIO()
    mem.write(json.dumps(data, indent=4).encode('utf-8'))
    mem.seek(0)
    
    return send_file(
        mem, 
        as_attachment=True, 
        download_name=f"{kit.name.replace(' ', '_')}.json", 
        mimetype='application/json'
    )

@app.route('/kit/import_json', methods=['POST'])
@login_required
def import_kit_json():
    """Import a kit from JSON, creating missing items."""
    if 'kit_file' not in request.files:
        return redirect(url_for('index'))
        
    file = request.files['kit_file']
    if file.filename == '':
        return redirect(url_for('index'))

    try:
        data = json.load(file)
        new_item_ids = []
        
        # Process items
        for item_data in data.get('items', []):
            # Check if item exists by name (to avoid duplicates)
            existing_item = Item.query.filter_by(name=item_data['name'], user_id=current_user.id).first()
            if existing_item:
                new_item_ids.append(str(existing_item.id))
            else:
                # Create new item
                new_item = Item(name=item_data['name'], category=item_data['category'], 
                                weight=item_data['weight'], cost=item_data['cost'], 
                                notes=item_data['notes'], image_filename=item_data.get('image_filename'), user_id=current_user.id)
                db.session.add(new_item)
                db.session.flush() # Get ID without committing
                new_item_ids.append(str(new_item.id))
        
        # Create Kit
        # Calculate totals based on the actual items we found/created
        items_objects = Item.query.filter(Item.id.in_(new_item_ids)).all()
        total_weight = sum(i.weight for i in items_objects)
        total_cost = sum(i.cost for i in items_objects)
        
        new_kit = Kit(name=data.get('name', 'Imported Kit'), 
                      notes=data.get('notes', ''),
                      total_weight=total_weight, 
                      total_cost=total_cost, 
                      item_ids=",".join(new_item_ids),
                      user_id=current_user.id)
        
        db.session.add(new_kit)
        db.session.commit()
        
    except Exception as e:
        print(f"Error importing kit: {e}")
        
    return redirect(url_for('index'))

@app.route('/kit/<int:kit_id>/pdf')
@login_required
def export_kit_pdf(kit_id):
    kit = Kit.query.get_or_404(kit_id)
    if kit.user_id != current_user.id: return redirect(url_for('index'))
    # Parse IDs
    item_ids = [int(i) for i in kit.item_ids.split(',') if i]
    items_in_db = Item.query.filter(Item.id.in_(item_ids)).all()
    items_map = {item.id: item for item in items_in_db}
    kit_items = [items_map[i_id] for i_id in item_ids if i_id in items_map]
    
    settings = Settings.query.filter_by(user_id=current_user.id).first()
    currency = settings.currency_symbol if settings else '£'
    is_imperial = settings.weight_unit == 'imperial' if settings else False
    username = settings.username if settings else None

    # --- Custom Header/Footer Drawing Function ---
    def draw_header_footer(canvas, doc):
        canvas.saveState()
        w, h = doc.pagesize
        
        # Theme Colors
        dark_header = colors.HexColor('#2F3E28') # Dark Forest Green
        olive_accent = colors.HexColor('#6b8e23') # App Primary
        
        # 1. Draw Header Background
        header_height = 80
        canvas.setFillColor(dark_header)
        canvas.rect(0, h - header_height, w, header_height, fill=1, stroke=0)
        
        # 2. Draw Subtle Mountain Graphics (Right side of header)
        canvas.setFillColor(colors.HexColor('#3A4C32')) # Slightly lighter green
        # Mountain 1
        p1 = canvas.beginPath()
        p1.moveTo(w-180, h-header_height)
        p1.lineTo(w-90, h-20)
        p1.lineTo(w, h-header_height)
        p1.close()
        canvas.drawPath(p1, fill=1, stroke=0)
        # Mountain 2
        p2 = canvas.beginPath()
        p2.moveTo(w-280, h-header_height)
        p2.lineTo(w-200, h-40)
        p2.lineTo(w-120, h-header_height)
        p2.close()
        canvas.drawPath(p2, fill=1, stroke=0)

        # 3. Header Text
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 26)
        canvas.drawString(30, h - 45, f"{kit.name}")
        
        if username:
            canvas.setFont("Helvetica", 12)
            canvas.setFillColor(colors.HexColor('#cfd8dc')) # Light grey
            canvas.drawString(30, h - 65, f"Pack List by {username}")
            
        # 4. Accent Line at bottom of header
        canvas.setStrokeColor(olive_accent)
        canvas.setLineWidth(4)
        canvas.line(0, h - header_height, w, h - header_height)
        
        # 5. Footer
        canvas.setFillColor(colors.gray)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(w/2, 15, "Generated by BaseWeight")
        
        canvas.restoreState()

    # --- Dynamic Scaling Logic ---
    # Calculate sizes based on item count to ensure 1-page fit
    item_count = len(kit_items)
    
    if item_count > 45:
        row_font_size = 5
        row_leading = 6
        row_padding = 0.5
        chart_height = 70
        pie_size = 60
    elif item_count > 25:
        row_font_size = 6
        row_leading = 7
        row_padding = 1
        chart_height = 90
        pie_size = 80
    else:
        row_font_size = 8
        row_leading = 9
        row_padding = 3
        chart_height = 110
        pie_size = 100

    buffer = io.BytesIO()
    # Reduced topMargin to 90pt (Header is 80pt)
    doc = SimpleDocTemplate(buffer, pagesize=portrait(letter),
                            rightMargin=20, leftMargin=20, topMargin=90, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()
    # Create a compact style for table text
    compact_style = styles['BodyText']
    compact_style.fontSize = row_font_size
    compact_style.leading = row_leading

    # --- Style Definitions ---
    # Match App Theme: Olive Primary (#6b8e23)
    olive_color = colors.HexColor('#6b8e23')
    
    title_style = styles['Title']
    title_style.textColor = olive_color
    
    # --- 1. Dashboard (Side-by-Side) ---
    if is_imperial:
        lbs = kit.total_weight * 0.00220462
        oz = kit.total_weight * 0.035274
        w_str = f"{lbs:.2f} lbs ({oz:.1f} oz)"
    else:
        kg = kit.total_weight / 1000
        w_str = f"{kg:.2f} kg ({int(kit.total_weight)} g)"
    
    # Left Side: Summary Text
    summary_content = [
        [Paragraph('Total Weight', styles['Normal'])],
        [Paragraph(f'<font size=12 color="#6b8e23"><b>{w_str}</b></font>', styles['Normal'])],
        [Paragraph('', styles['Normal'])], # Spacer
        [Paragraph('Total Cost', styles['Normal'])],
        [Paragraph(f'<font size=12 color="#6b8e23"><b>{currency}{kit.total_cost:.2f}</b></font>', styles['Normal'])]
    ]
    summary_table = Table(summary_content, colWidths=[150])
    summary_table.setStyle(TableStyle([
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))

    # Right Side: Pie Chart
    chart_flowable = Spacer(1, 1)
    
    # Sort items by weight descending and take top 5
    top_items = sorted(kit_items, key=lambda x: x.weight, reverse=True)[:5]
    total_weight = sum(i.weight for i in kit_items)

    if top_items and total_weight > 0:
        data = [item.weight for item in top_items]
        labels = []
        for item in top_items:
            pct = (item.weight / total_weight) * 100
            labels.append(f"{item.name} ({pct:.1f}%)")
        
        # Compact Drawing
        drawing = Drawing(350, chart_height)
        pie = Pie()
        pie.x = 10
        pie.y = 5
        pie.width = pie_size
        pie.height = pie_size
        pie.data = data
        pie.labels = None
        
        # App Palette
        palette = [
            colors.HexColor('#6b8e23'), colors.HexColor('#556b2f'), colors.HexColor('#8fbc8f'), 
            colors.HexColor('#2e8b57'), colors.HexColor('#daa520'), colors.HexColor('#cd853f'), 
            colors.HexColor('#8b4513'), colors.HexColor('#a0522d'), colors.HexColor('#4682b4'), 
            colors.HexColor('#5f9ea0')
        ]
        for i, val in enumerate(pie.data):
            pie.slices[i].fillColor = palette[i % len(palette)]
            pie.slices[i].strokeColor = colors.white
            pie.slices[i].strokeWidth = 1

        # Legend
        legend = Legend()
        legend.x = 130
        legend.y = pie_size
        legend.dx = 8
        legend.dy = 8
        legend.fontName = 'Helvetica'
        legend.fontSize = 8
        legend.boxAnchor = 'nw'
        legend.columnMaximum = 8
        legend.colorNamePairs = [(pie.slices[i].fillColor, labels[i]) for i in range(len(labels))]
        
        drawing.add(pie)
        drawing.add(legend)
        
        # Add title above chart
        title_style = styles['Normal']
        title_style.alignment = 1 # Center
        chart_flowable = [Paragraph("Top 5 Heaviest Items (%)", title_style), Spacer(1, 5), drawing]

    # Combine Summary and Chart into one row
    dash_data = [[summary_table, chart_flowable]]
    dash_table = Table(dash_data, colWidths=[150, 380])
    dash_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(dash_table)
    elements.append(Spacer(1, 5))

    # --- 3. Item Table ---
    data = [['Category', 'Item', 'Notes', 'Weight', f'Cost ({currency})']]
    
    for item in kit_items:
        if is_imperial:
            lbs = item.weight * 0.00220462
            iw_str = f"{lbs:.2f} lbs"
        else:
            iw_str = f"{int(item.weight)} g"
            
        data.append([
            Paragraph(item.category, compact_style),
            Paragraph(item.name, compact_style),
            Paragraph(item.notes or "", compact_style),
            iw_str,
            f"{item.cost:.2f}"
        ])

    # Table Style
    table = Table(data, colWidths=[70, 130, 130, 70, 60])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), olive_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), row_font_size),
        ('BOTTOMPADDING', (0, 0), (-1, 0), row_padding),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    elements.append(table)
    doc.build(elements, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
    
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{kit.name.replace(' ', '_')}.pdf", mimetype='application/pdf')

@app.route('/shutdown')
def shutdown():
    """Forcefully shuts down the application."""
    import os
    os._exit(0)
    return "Application closing..."

def seed_database(user_id):
    """Populate the database with initial data if empty."""
    if Item.query.filter_by(user_id=user_id).first():
        return

    items_data = [
        # Backpacks
        {"name": "Helikon-Tex Summit Backpack", "weight": 1300, "cost": 112, "notes": "40L", "category": "Backpack"},
        {"name": "Osprey Kestrel 58", "weight": 2131, "cost": 220, "notes": "", "category": "Backpack"},
        {"name": "Osprey Aether 55", "weight": 2200, "cost": 265, "notes": "", "category": "Backpack"},
        {"name": "Highlander Waterproof Pack Liner", "weight": 55, "cost": 2.5, "notes": "", "category": "Backpack"},
        
        # Chestpack
        {"name": "Helikon-Tex Numbat Chest pack", "weight": 490, "cost": 60, "notes": "", "category": "Chestpack"},
        {"name": "Chest pack items", "weight": 650, "cost": 0, "notes": "keys(66g), phone (221g), inhaler (30g), knife(42g), snack, torch(145g), wallet (68g), headphones (73g)", "category": "Chestpack"},

        # Clothing
        {"name": "Sleeping clothes", "weight": 1000, "cost": 0, "notes": "t-shirt, thermal leggins, thermal top, seal-skin socks", "category": "Clothing"},
        {"name": "Spare clothes", "weight": 500, "cost": 0, "notes": "t-shirt, underwear, hiking socks", "category": "Clothing"},
        {"name": "Warm Gloves", "weight": 100, "cost": 0, "notes": "", "category": "Clothing"},

        # Comfort
        {"name": "Mountain Warehouse sit pad", "weight": 105, "cost": 7, "notes": "Small foldable foam sit pad for sitting around camp", "category": "Comfort"},
        {"name": "Flip-flops", "weight": 100, "cost": 10, "notes": "Light flip-flops to wear at camp", "category": "Comfort"},

        # Cook System
        {"name": "Cooking kit (trangia)", "weight": 600, "cost": 50, "notes": "Trangia, pot stand, foil for trangia to stand on, windshield, Ti pot, lighter, silicone fingers, Meths (300ml), spong/cloth, sea to summit collapsing mug, Ti spoon", "category": "Cook System"},
        {"name": "Alpkit Koro Stove", "weight": 124, "cost": 59.99, "notes": "", "category": "Cook System"},
        {"name": "Methylated Spirit (250ml)", "weight": 250, "cost": 5, "notes": "For Trangia", "category": "Cook System"},
        {"name": "Trangia Stove", "weight": 110, "cost": 17, "notes": "Yellow plastic bag included in weighing", "category": "Cook System"},
        {"name": "Windshield (2-piece)", "weight": 50, "cost": 9.99, "notes": "Circular winshield in 2 pieces. DIY aluminuim pot stands", "category": "Cook System"},
        {"name": "Sea to Summit (200ml) cup", "weight": 40, "cost": 12, "notes": "", "category": "Cook System"},
        {"name": "Lixada Titanium pot (Packed)", "weight": 148, "cost": 25, "notes": "Bag & trangia trap included in weight. Pot on its own weight 112g", "category": "Cook System"},
        {"name": "Lixada Titanium pot (600ml)", "weight": 112, "cost": 25, "notes": "Pot on its own", "category": "Cook System"},
        {"name": "Alpkit Concertina windshield", "weight": 104, "cost": 12.99, "notes": "", "category": "Cook System"},
        {"name": "Silicone finger cover", "weight": 8.4, "cost": 2.5, "notes": "Small silicone finger covers for holding hot pots", "category": "Cook System"},
        {"name": "Ferrocerium rod", "weight": 24.6, "cost": 0, "notes": "Fero rod for striking as firelighter (spare if lighter breaks)", "category": "Cook System"},
        {"name": "Fireproof mat", "weight": 5.3, "cost": 0, "notes": "Small alluminium mat to put Trangia stove on", "category": "Cook System"},
        {"name": "Lighter", "weight": 15, "cost": 0, "notes": "Cheap disposable lighter", "category": "Cook System"},
        {"name": "Trangia pot strap", "weight": 21.3, "cost": 9, "notes": "Strap to keep the Ti pot closed", "category": "Cook System"},
        {"name": "Cloth/Sponge", "weight": 13, "cost": 0, "notes": "Small yellow cloth and sponge for cleaning/drying", "category": "Cook System"},

        # Commodities
        {"name": "Accesories pouch", "weight": 900, "cost": 100, "notes": "Pillow, eye mask, hand warmers, tent light, mosquito net, ear plugs, toiletories (toothbrush / toothpaste / anti-histomines), tissues, powerbank & cable", "category": "Commodities"},
        {"name": "Toiletry bag", "weight": 106, "cost": 0, "notes": "Condom, comb, travel toothpaste, toothbrush, tissues, anti-histomine", "category": "Commodities"},
        {"name": "Food", "weight": 1000, "cost": 0, "notes": "Varies depending on trip", "category": "Commodities"},
        {"name": "Alpkit Turbo pump", "weight": 100, "cost": 27.99, "notes": "Small bettery pump with light on", "category": "Commodities"},
        {"name": "Folding sit mat", "weight": 125, "cost": 9.99, "notes": "small pad to sit on", "category": "Commodities"},
        {"name": "OEX Bugnet", "weight": 33, "cost": 5, "notes": "", "category": "Commodities"},
        {"name": "Anker PowerCore 20100", "weight": 356, "cost": 40, "notes": "Small cable also", "category": "Commodities"},
        {"name": "Hand Warmers", "weight": 45, "cost": 0, "notes": "x2 hand warmers, usually keep 4 in pack", "category": "Commodities"},

        # Shelter
        {"name": "DD Hammocks 3x2.9 tarp superlite", "weight": 490, "cost": 77, "notes": "", "category": "Shelter"},
        {"name": "Guy ropes", "weight": 102, "cost": 20, "notes": "6 Guy ropes, x3 4m, x3 2m.", "category": "Shelter"},
        {"name": "Tent pegs", "weight": 237, "cost": 0, "notes": "Mix of 'V', 'Y', and shep hook pegs (x 20). ", "category": "Shelter"},
        {"name": "Alpkit Elan hooped bivvy", "weight": 900, "cost": 110, "notes": "", "category": "Shelter"},
        {"name": "OEX Lynx EV II Ground sheet", "weight": 220, "cost": 44, "notes": "", "category": "Shelter"},
        {"name": "FORCLAZ MT900 Trekking Pole", "weight": 275, "cost": 40, "notes": "", "category": "Shelter"},
        {"name": "FORCLAZ MT500 Trekking Pole", "weight": 240, "cost": 17, "notes": "", "category": "Shelter"},
        {"name": "3F UL Gear LanShan 2 Tent 2026 (3S)", "weight": 1150, "cost": 106, "notes": "", "category": "Shelter"},
        {"name": "3F UL Gear LanShan 1 Tent (3S)", "weight": 930, "cost": 145, "notes": "", "category": "Shelter"},
        {"name": "Vango Helvellyn 300 Tent", "weight": 3300, "cost": 245, "notes": "", "category": "Shelter"},
        {"name": "Vango Helvellyn 200 Tent", "weight": 2600, "cost": 200, "notes": "4-season, high wind, heavy", "category": "Shelter"},
        {"name": "Vango Helvellyn 200 Ground sheet", "weight": 300, "cost": 30, "notes": "", "category": "Shelter"},
        {"name": "Alpkit Tetri Tent", "weight": 3000, "cost": 159.99, "notes": "", "category": "Shelter"},
        {"name": "MSR Access 2 Tent", "weight": 1640, "cost": 584.99, "notes": "", "category": "Shelter"},

        # Sleep System
        {"name": "Simmand MT900 sleeping bag", "weight": 945, "cost": 170, "notes": "0*C", "category": "Sleep System"},
        {"name": "Highlander Reflective Camping Mat", "weight": 115, "cost": 10, "notes": "", "category": "Sleep System"},
        {"name": "OEX Traverse Self-Inflating Mat", "weight": 970, "cost": 20, "notes": "", "category": "Sleep System"},
        {"name": "OEX Traverse IMX Sleeping Mat", "weight": 410, "cost": 70, "notes": "", "category": "Sleep System"},
        {"name": "OEX Furnace 8+ Sleeping Bag Liner", "weight": 425, "cost": 38, "notes": "", "category": "Sleep System"},
        {"name": "Highlander Nap Pak Arctic Air Mat", "weight": 900, "cost": 99.99, "notes": "", "category": "Sleep System"},
        {"name": "Alpkit Radient Mat (R-7.2)", "weight": 640, "cost": 109.99, "notes": "4-Season", "category": "Sleep System"},
        {"name": "Alpkit Whisper Mat (No R-Value)", "weight": 740, "cost": 83.99, "notes": "", "category": "Sleep System"},
        {"name": "Alpkit Numo (No R-Value)", "weight": 350, "cost": 49.99, "notes": "", "category": "Sleep System"},
        {"name": "Alpkit Pump (20L)", "weight": 121, "cost": 14.99, "notes": "Drybag used as air pump for sleeping mat", "category": "Sleep System"},
        {"name": "Exped Ultra Pillow", "weight": 68, "cost": 40, "notes": "", "category": "Sleep System"},
        {"name": "FORCLAZ - Blue Solid Eyemask", "weight": 10, "cost": 10, "notes": "", "category": "Sleep System"},
        {"name": "Forclaz Eyemask", "weight": 20, "cost": 0, "notes": "", "category": "Sleep System"},
        {"name": "Cheap earplug", "weight": 6.2, "cost": 0, "notes": "Used during sleep help with wind noise on tent", "category": "Sleep System"},

        # Water
        {"name": "Water bladder (2L)", "weight": 2000, "cost": 0, "notes": "", "category": "Water"},
        {"name": "Water bottle (1L)", "weight": 1000, "cost": 0, "notes": "", "category": "Water"},
        {"name": "Katadyn Water Filter", "weight": 59, "cost": 50, "notes": "", "category": "Water"},

        # Lighting
        {"name": "Tent lantern", "weight": 80, "cost": 3, "notes": "Small light for sitting in the tent", "category": "Lighting"},
        {"name": "Sofirm SP40", "weight": 145, "cost": 25, "notes": "LED rechargable torch that can be used as headtorch", "category": "Lighting"},
        {"name": "LED Lenser TT", "weight": 130, "cost": 45, "notes": "LED hand torch - disposible battery", "category": "Lighting"},
    ]

    for item in items_data:
        db.session.add(Item(**item, user_id=user_id))
    
    db.session.commit()
    print("Database seeded with initial inventory!")

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Creates the DB file if it doesn't exist
        
        # Migration: Check if image_filename column exists, if not add it
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT image_filename FROM item LIMIT 1"))
        except Exception:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE item ADD COLUMN image_filename VARCHAR(255)"))
                conn.commit()
                print("Database updated: Added image_filename column.")
        
        # Migration: Check if username column exists in settings, if not add it
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT username FROM settings LIMIT 1"))
        except Exception:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE settings ADD COLUMN username VARCHAR(100)"))
                conn.commit()
                print("Database updated: Added username column to settings.")

        # Migration: Check if notes column exists in kit, if not add it
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT notes FROM kit LIMIT 1"))
        except Exception:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE kit ADD COLUMN notes TEXT"))
                conn.commit()
                print("Database updated: Added notes column to kit.")
        
        # Migration: Check if user_id column exists in item, if not add it
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT user_id FROM item LIMIT 1"))
        except Exception:
            with db.engine.connect() as conn:
                for table in ['item', 'kit', 'settings']:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))
                conn.commit()
                print("Database updated: Added user_id columns.")

            seed_database()
    
    # Find a free port dynamically
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('localhost', 0))
    port = sock.getsockname()[1]
    sock.close()

    if getattr(sys, 'frozen', False):
        import webbrowser
        from threading import Timer
        Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
        app.run(port=port, debug=False)
    else:
        app.run(port=port, debug=True)
