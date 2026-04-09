import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g

app = Flask(__name__)
app.secret_key = 'super-secret-key-for-prototype'

import shutil

if os.environ.get('VERCEL') == '1':
    DATABASE = '/tmp/shop.db'
    original_db = os.path.join(os.path.dirname(__file__), 'shop.db')
    if not os.path.exists(DATABASE) and os.path.exists(original_db):
        shutil.copyfile(original_db, DATABASE)
else:
    DATABASE = os.path.join(os.path.dirname(__file__), 'shop.db')

try:
    import libsql_experimental
except ImportError:
    libsql_experimental = None

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        turso_url = os.environ.get('TURSO_DATABASE_URL')
        turso_auth_token = os.environ.get('TURSO_AUTH_TOKEN')
        
        if turso_url and libsql_experimental:
            db = g._database = libsql_experimental.connect(turso_url, auth_token=turso_auth_token)
        else:
            db = g._database = sqlite3.connect(DATABASE)
            
    return db

def query_db(query, args=(), one=False):
    db = get_db()
    cur = db.execute(query, args)
    rv = cur.fetchall()
    if not cur.description:
        return rv
    columns = [col[0] for col in cur.description]
    res = [dict(zip(columns, row)) for row in rv]
    return (res[0] if res else None) if one else res

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        with open(schema_path, 'r') as f:
            db.executescript(f.read())
        db.commit()

@app.route('/')
def index():
    return redirect(url_for('cashier'))

@app.route('/cashier', methods=['GET', 'POST'])
def cashier():
    db = get_db()
    if request.method == 'POST':
        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        
        if not product_ids:
            return redirect(url_for('cashier'))
            
        cur = db.cursor()
        cur.execute("INSERT INTO sales DEFAULT VALUES")
        sale_id = cur.lastrowid
        
        for pid, qty in zip(product_ids, quantities):
            if not pid or not qty: continue
            pid = int(pid)
            try:
                qty = int(qty)
            except ValueError:
                continue
                
            if qty < 1: continue
            
            product = query_db("SELECT price FROM products WHERE id = ?", (pid,), one=True)
            if product:
                price = product['price']
                cur.execute("INSERT INTO sale_items (sale_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                            (sale_id, pid, qty, price))
                cur.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, pid))
        
        db.commit()
        return redirect(url_for('cashier'))
        
    products = query_db('SELECT * FROM products ORDER BY name')
    return render_template('cashier.html', products=products)

@app.route('/dashboard')
def dashboard():
    db = get_db()
    
    todays_sales_query = """
        SELECT p.name, si.quantity, si.unit_price, (si.quantity * si.unit_price) as subtotal
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        JOIN products p ON si.product_id = p.id
        WHERE date(s.created_at, 'localtime') = date('now', 'localtime')
    """
    todays_sales = query_db(todays_sales_query)
    total_revenue = sum(row['subtotal'] for row in todays_sales)
    
    inventory = query_db('SELECT * FROM products ORDER BY stock ASC')
    
    return render_template('dashboard.html', 
                           todays_sales=todays_sales, 
                           total_revenue=total_revenue, 
                           inventory=inventory)

@app.route('/inventory', methods=['GET', 'POST'])
def inventory():
    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name')
            price = request.form.get('price')
            stock = request.form.get('stock')
            if name and price and stock:
                try:
                    db.execute('INSERT INTO products (name, price, stock) VALUES (?, ?, ?)',
                               (name, float(price), int(stock)))
                    db.commit()
                except sqlite3.IntegrityError:
                    pass
        elif action == 'update':
            pid = request.form.get('product_id')
            price = request.form.get('price')
            stock = request.form.get('stock')
            if pid and price and stock:
                db.execute('UPDATE products SET price = ?, stock = ? WHERE id = ?',
                           (float(price), int(stock), int(pid)))
                db.commit()
        return redirect(url_for('inventory'))
        
    products = query_db('SELECT * FROM products ORDER BY name')
    return render_template('inventory.html', products=products)

@app.route('/revenue')
def revenue():
    db = get_db()
    
    query = """
        SELECT date(s.created_at, 'localtime') as day, SUM(si.quantity * si.unit_price) as total
        FROM sales s
        JOIN sale_items si ON s.id = si.sale_id
        WHERE date(s.created_at, 'localtime') >= date('now', '-30 days', 'localtime')
        GROUP BY day
        ORDER BY day ASC
    """
    results = query_db(query)
    
    dates = [row['day'] for row in results]
    revenues = [row['total'] for row in results]
    
    return render_template('revenue.html', dates=dates, revenues=revenues, results=results)

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
        with app.app_context():
            db = get_db()
            db.execute("INSERT INTO products (name, price, stock) VALUES ('rice', 65, 45)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('wheat flour', 45, 50)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('milk', 60, 55)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('cooking oil', 155, 40)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('sugar', 45, 60)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('eggs', 85, 48)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('bread', 40, 52)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('bath soap', 35, 58)")
            db.execute("INSERT INTO products (name, price, stock) VALUES ('salt', 20, 42)")
            db.commit()
            
    app.run(debug=True, port=5000)
