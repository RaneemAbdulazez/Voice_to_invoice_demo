import sqlite3

def init_database():
    conn = sqlite3.connect('inventory.db')
    cursor = conn.cursor()

    # 1. DELETE THE OLD TABLE (This clears everything!)
    cursor.execute('DROP TABLE IF EXISTS products')

    # 2. CREATE THE TABLE FRESH
    cursor.execute('''
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode_data TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            sku TEXT UNIQUE NOT NULL,
            price REAL NOT NULL
        )
    ''')

    # New Plumbing Inventory
    sample_products = [
        ("PRODUCT-001", "PEX Pipe 1/2-in x 100-ft", "PEX-9901", 38.50),
        ("PRODUCT-002", "Quarter-Turn Ball Valve", "VAL-1102", 12.00),
        ("PRODUCT-003", "Teflon Thread Tape", "TAP-5503", 2.49),
        ("PRODUCT-004", "Adjustable Pipe Wrench", "WRN-4404", 28.00),
        ("PRODUCT-005", "Wax Toilet Ring", "WAX-3305", 6.50),
        ("PRODUCT-006", "Kitchen Faucet Sprayer", "FCT-2206", 115.99),
        ("PRODUCT-007", "PVC Primer & Cement Kit", "GLU-7707", 14.00),
        ("PRODUCT-008", "Tankless Water Heater", "HTR-8808", 650.00),
        ("PRODUCT-009", "Plumber's Putty 14oz", "PTY-6609", 5.00),
        ("PRODUCT-010", "Garbage Disposal 1/2 HP", "DSP-0010", 95.00)
    ]

    try:
        cursor.executemany('''
            INSERT INTO products (barcode_data, name, sku, price) 
            VALUES (?, ?, ?, ?)
        ''', sample_products)
        conn.commit()
        print("✅ Old data cleared and plumbing products installed!")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_database()