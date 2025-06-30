# app.py

import os
from flask import Flask, render_template, request, send_from_directory, flash, redirect, url_for
from PIL import Image
from werkzeug.utils import secure_filename
import math

# --- Konfigurasi Aplikasi Flask ---
app = Flask(__name__)
app.secret_key = "supersecretkey"  # Diperlukan untuk flash messages
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['RESULT_FOLDER'] = 'results/'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}

# Pastikan folder untuk upload dan hasil ada
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULT_FOLDER'], exist_ok=True)


# --- Fungsi Helper ---
def allowed_file(filename):
    """Memeriksa apakah ekstensi file diizinkan."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def text_to_binary(text):
    """Mengubah string teks ke representasi biner."""
    return ''.join(format(ord(char), '08b') for char in text)

def binary_to_text(binary_str):
    """Mengubah representasi biner kembali ke string teks."""
    # Pastikan panjang biner kelipatan 8
    if len(binary_str) % 8 != 0:
        binary_str = binary_str[:-(len(binary_str) % 8)]
    
    # Periksa karakter non-printable di akhir
    text = ""
    for i in range(0, len(binary_str), 8):
        byte = binary_str[i:i+8]
        try:
            char_code = int(byte, 2)
            if 0 <= char_code <= 127: # Hanya ASCII dasar
                 text += chr(char_code)
            else:
                # Menghentikan jika menemukan byte yang tidak valid atau di luar jangkauan
                break
        except (ValueError, TypeError):
            # Menghentikan jika ada kesalahan konversi
            break
    return text


# --- Implementasi Algoritma Edge Mean Difference (EMD) ---

# Tabel rentang untuk menentukan berapa bit yang disisipkan.
# Format: (batas_bawah, batas_atas, jumlah_bit)
RANGES = [
    (0, 7, 3), 
    (8, 15, 3), 
    (16, 31, 4), 
    (32, 63, 5), 
    (64, 127, 6), 
    (128, 255, 7)
]

def get_embed_info(difference):
    """Mendapatkan jumlah bit yang bisa disisipkan berdasarkan selisih piksel."""
    abs_diff = abs(difference)
    for lower, upper, bits in RANGES:
        if lower <= abs_diff <= upper:
            return bits
    return 0

DELIMITER = "|||END|||"

def embed_emd(image_path, message, result_path):
    """Menyisipkan pesan ke dalam gambar menggunakan EMD."""
    try:
        img = Image.open(image_path).convert('RGB')
        pixels = list(img.getdata())
        width, height = img.size

        # Tambahkan delimiter untuk menandai akhir pesan
        binary_message = text_to_binary(message + DELIMITER)
        
        # Hitung kapasitas maksimum
        capacity = 0
        for i in range(0, len(pixels) - 1, 2):
            for c in range(3): # Loop untuk channel R, G, B
                p1 = pixels[i][c]
                p2 = pixels[i+1][c]
                diff = p1 - p2
                capacity += get_embed_info(diff)

        if len(binary_message) > capacity:
            return False, "Pesan terlalu panjang untuk disisipkan pada gambar ini."

        msg_idx = 0
        new_pixels = []
        
        # Iterasi per 2 piksel (pixel pair)
        for i in range(0, len(pixels) - 1, 2):
            # Jika semua pesan sudah disisipkan, salin sisa piksel
            if msg_idx >= len(binary_message):
                new_pixels.append(pixels[i])
                new_pixels.append(pixels[i+1])
                continue

            p1_rgb = list(pixels[i])
            p2_rgb = list(pixels[i+1])

            # Proses setiap channel (R, G, B)
            for c in range(3):
                if msg_idx >= len(binary_message):
                    break
                
                p1, p2 = p1_rgb[c], p2_rgb[c]
                diff = p1 - p2
                
                n_bits = get_embed_info(diff)
                if n_bits == 0:
                    continue
                
                # Ambil n_bits dari pesan
                segment = binary_message[msg_idx:msg_idx + n_bits]
                if len(segment) < n_bits:
                    # Jika sisa pesan lebih sedikit dari n_bits, lewati
                    continue
                    
                b = int(segment, 2)
                
                # Hitung selisih baru d'
                m = 2**n_bits
                d_prime = m * (diff // m) + b
                if abs(d_prime - diff) > m/2 and diff < d_prime:
                    d_prime -= m
                elif abs(d_prime - diff) > m/2 and diff > d_prime:
                    d_prime += m

                # Modifikasi piksel
                g1 = math.ceil((d_prime - diff) / 2)
                g2 = -math.floor((d_prime - diff) / 2)

                p1_new = p1 + g1
                p2_new = p2 + g2

                # Jaga agar nilai piksel tetap dalam rentang 0-255 (clamping)
                p1_rgb[c] = max(0, min(255, p1_new))
                p2_rgb[c] = max(0, min(255, p2_new))
                
                msg_idx += n_bits

            new_pixels.append(tuple(p1_rgb))
            new_pixels.append(tuple(p2_rgb))

        # Handle jika jumlah piksel ganjil
        if len(pixels) % 2 != 0:
            new_pixels.append(pixels[-1])

        new_img = Image.new('RGB', (width, height))
        new_img.putdata(new_pixels)
        new_img.save(result_path, 'PNG')
        
        return True, "Pesan berhasil disisipkan."

    except Exception as e:
        print(f"Error embedding: {e}")
        return False, f"Terjadi kesalahan saat proses penyisipan: {e}"


def extract_emd(image_path):
    """Mengekstrak pesan dari gambar menggunakan EMD."""
    try:
        img = Image.open(image_path).convert('RGB')
        pixels = list(img.getdata())
        
        binary_message = ""
        
        # Iterasi per 2 piksel
        for i in range(0, len(pixels) - 1, 2):
            p1_rgb = pixels[i]
            p2_rgb = pixels[i+1]
            
            for c in range(3): # Loop R, G, B
                p1, p2 = p1_rgb[c], p2_rgb[c]
                diff = p1 - p2
                
                n_bits = get_embed_info(diff)
                if n_bits == 0:
                    continue
                
                m = 2**n_bits
                b = diff % m
                
                binary_message += format(b, '0' + str(n_bits) + 'b')

                # Cek delimiter secara berkala untuk efisiensi
                if DELIMITER in binary_to_text(binary_message):
                    text_message = binary_to_text(binary_message)
                    return text_message.split(DELIMITER)[0]

        # Jika loop selesai dan delimiter tidak ditemukan
        return "Pesan tersembunyi tidak ditemukan atau gambar rusak."

    except Exception as e:
        print(f"Error extracting: {e}")
        return f"Gagal mengekstrak pesan: {e}"


# --- Rute Aplikasi Flask ---

@app.route('/')
def index():
    """Menampilkan halaman utama."""
    return render_template('index.html')

@app.route('/encode', methods=['POST'])
def encode():
    """Menangani proses penyisipan pesan."""
    if 'image' not in request.files or 'message' not in request.form:
        flash("Permintaan tidak lengkap.", 'danger')
        return redirect(url_for('index'))

    file = request.files['image']
    message = request.form['message']

    if file.filename == '' or message == '':
        flash("Gambar dan pesan tidak boleh kosong.", 'danger')
        return redirect(url_for('index'))

    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
        file.save(upload_path)

        result_filename = "stego_" + original_filename.split('.')[0] + ".png"
        result_path = os.path.join(app.config['RESULT_FOLDER'], result_filename)

        success, feedback_msg = embed_emd(upload_path, message, result_path)

        if success:
            flash(feedback_msg, 'success')
            return render_template(
                'index.html',
                show_result=True,
                original_image=original_filename,
                stego_image=result_filename
            )
        else:
            flash(feedback_msg, 'danger')
            return redirect(url_for('index'))

    else:
        flash("Format file tidak didukung. Gunakan PNG atau JPG.", 'danger')
        return redirect(url_for('index'))


@app.route('/decode', methods=['POST'])
def decode():
    """Menangani proses ekstraksi pesan."""
    if 'stego_image' not in request.files:
        flash("Permintaan tidak lengkap.", 'danger')
        return redirect(url_for('index'))

    file = request.files['stego_image']

    if file.filename == '':
        flash("Pilih gambar yang akan diekstrak pesannya.", 'danger')
        return redirect(url_for('index'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(upload_path)

        extracted_message = extract_emd(upload_path)

        flash("Proses ekstraksi selesai.", 'info')
        return render_template(
            'index.html',
            show_decode_result=True,
            extracted_message=extracted_message
        )
    else:
        flash("Format file tidak didukung.", 'danger')
        return redirect(url_for('index'))

@app.route('/download/<filename>')
def download(filename):
    """Menyediakan file hasil steganografi untuk diunduh."""
    return send_from_directory(app.config['RESULT_FOLDER'], filename, as_attachment=True)
    
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Menampilkan gambar yang diunggah (asli)."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/results/<filename>')
def result_file(filename):
    """Menampilkan gambar hasil steganografi."""
    return send_from_directory(app.config['RESULT_FOLDER'], filename)


if __name__ == '__main__':
    app.run(debug=True)