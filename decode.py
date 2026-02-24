import cv2
import numpy as np
import sqlite3
import os
from pyzbar.pyzbar import decode
from pdf2image import convert_from_path
from datetime import datetime

# --- Configuration ---
DB_NAME = "plumbing_inventory.db"
# Path for your WSL environment
PDF_INPUT_PATH = "/home/raneem/barcodeGen/barcodes_list.pdf"

# List of 10 specific plumbing items for your Voice-to-Invoice project
PLUMBING_ITEMS = [
    "Copper Pipe 1/2 inch (10ft)",
    "PEX Tee Connector 3/4 inch",
    "PVC Sweep Elbow 2 inch",
    "Kitchen Sink Drain Kit",
    "Shut-off Ball Valve 1/2 inch",
    "Thread Sealant Tape (Teflon)",
    "Adjustable Pipe Wrench 12 inch",
    "Toilet Wax Ring with Bolts",
    "Braided Stainless Steel Hose",
    "Shower Mixing Valve Cartridge"
]

def initialize_database():
    """Sets up the SQLite database with a UNIQUE constraint on barcodes."""
    connection = sqlite3.connect(DB_NAME)
    # Corrected: cursor comes directly from the connection
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT,
            barcode_data TEXT UNIQUE,
            scanned_at TIMESTAMP
        )
    ''')
    connection.commit()
    return connection

def process_barcodes():
    # 1. Check if the PDF file exists
    if not os.path.exists(PDF_INPUT_PATH):
        print(f"Error: File not found at {PDF_INPUT_PATH}")
        return

    # 2. Connect to Database
    db_conn = initialize_database()
    cursor = db_conn.cursor()
    
    print(f"--- Starting processing: {os.path.basename(PDF_INPUT_PATH)} ---")

    try:
        # 3. Convert PDF pages to images
        pages = convert_from_path(PDF_INPUT_PATH)
        item_mapping_index = 0

        for page_number, page_image in enumerate(pages, 1):
            print(f"Scanning Page {page_number}...")

            # 4. Convert PIL Image to OpenCV BGR format
            cv_image = cv2.cvtColor(np.array(page_image), cv2.COLOR_RGB2BGR)

            # 5. Decode barcodes
            detected_barcodes = decode(cv_image)

            for barcode in detected_barcodes:
                raw_data = barcode.data.decode('utf-8')
                
                # Assign name from the 10 items list
                item_name = PLUMBING_ITEMS[item_mapping_index % len(PLUMBING_ITEMS)]
                item_mapping_index += 1
                
                # 6. Store in Database
                try:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute('''
                        INSERT INTO inventory (item_name, barcode_data, scanned_at)
                        VALUES (?, ?, ?)
                    ''', (item_name, raw_data, timestamp))
                    
                    db_conn.commit()
                    print(f"   ✅ SUCCESS: Recorded {item_name} (ID: {raw_data})")
                
                except sqlite3.IntegrityError:
                    # Prevents duplicate barcodes
                    print(f"   ⚠️ SKIPPED: Barcode {raw_data} already exists.")

    except Exception as error:
        print(f"❌ An unexpected error occurred: {error}")
    
    finally:
        db_conn.close()
        print("\n--- Process finished. Database connection closed. ---")

if __name__ == "__main__":
    process_barcodes()