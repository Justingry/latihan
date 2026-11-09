"""
=============================================================================
 pelacak_gestur.py
 Mata Kuliah : Realitas Virtual dan Realitas Augmentasi (SE.1) - INF124312
 Pertemuan 11 : Problema Antarmuka Pengguna  |  Pengayaan Python + Unity
 Prodi Informatika - Fakultas Ilmu Komputer - UPN Veteran Jakarta

 LAPIS KECERDASAN (DENGAN DUKUNGAN 2 TANGAN).
 Membaca webcam, menemukan tangan, lalu menerjemahkan bentuk tangan menjadi
 nama gestur. Hasilnya dikirim ke Unity lewat UDP.

 ---------------------------------------------------------------------------
 PERUBAHAN MULTI-TANGAN:
 Script ini mengirimkan JSON berformat array (daftar) untuk menampung
 0, 1, atau 2 tangan sekaligus. Contoh keluaran yang dikirim:
 {
   "waktu": 12.345,
   "data": [
     {"gestur": "TERBUKA", "confidence": 0.98, "stabil": true, "tangan": "Right", "x": 0.5, "y": 0.4},
     {"gestur": "JEMPOL", "confidence": 0.85, "stabil": true, "tangan": "Left", "x": 0.2, "y": 0.6}
   ]
 }
 Pastikan script C# di Unity diperbarui untuk membaca format JSON ini!
=============================================================================
"""

import argparse
import json
import os
import socket
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

# --------------------------------------------------------------------------
# Berkas model.
# --------------------------------------------------------------------------
NAMA_MODEL = "hand_landmarker.task"
URL_MODEL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")

# --------------------------------------------------------------------------
# Nomor titik tangan menurut MediaPipe.
# --------------------------------------------------------------------------
PERGELANGAN = 0
PANGKAL_KELINGKING = 17
TELUNJUK_TIP = 8
JEMPOL_TIP, JEMPOL_IP = 4, 3
EMPAT_JARI = [
    ("telunjuk", 8, 6),
    ("tengah", 12, 10),
    ("manis", 16, 14),
    ("kelingking", 20, 18),
]

POLA_GESTUR = {
    (True, True, True, True, True): "TERBUKA",
    (False, False, False, False, False): "KEPAL",
    (False, True, False, False, False): "TUNJUK",
    (False, True, True, False, False): "DAMAI",
    (True, False, False, False, False): "JEMPOL",
    (True, True, False, False, False): "SARANGHAEYO",
    (True, True, False, False, True): "HIDUP JOKOWI",
    (False, False, True, False, False): "FUCK",
    (False, True, True, True, False): "Three Fingers Salute",
}
AMBANG_LURUS = 1.05
LEBAR_KEYAKINAN = 0.30


def siapkan_model(path):
    if os.path.exists(path):
        return True

    print(f"Berkas model belum ada. Mengunduh ke {path} ...")
    try:
        urllib.request.urlretrieve(URL_MODEL, path)
        ukuran = os.path.getsize(path) / 1_000_000
        print(f"Selesai, {ukuran:.1f} MB.")
        return True
    except Exception as e:
        print("\nGAGAL mengunduh berkas model.")
        print(f"  Sebab: {e}")
        return False


def pilih_backend(nama):
    peta = {
        "auto": cv2.CAP_ANY,
        "dshow": getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY),
        "msmf": getattr(cv2, "CAP_MSMF", cv2.CAP_ANY),
        "v4l2": getattr(cv2, "CAP_V4L2", cv2.CAP_ANY),
    }
    return peta.get(nama, cv2.CAP_ANY)


def buka_kamera(nomor, backend, lebar, tinggi):
    kamera = cv2.VideoCapture(nomor, pilih_backend(backend))
    if not kamera.isOpened():
        return None
    try:
        kamera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    except Exception:
        pass
    kamera.set(cv2.CAP_PROP_FRAME_WIDTH, lebar)
    kamera.set(cv2.CAP_PROP_FRAME_HEIGHT, tinggi)
    return kamera


def daftar_kamera(backend, sampai=5):
    print(f"Memeriksa kamera dengan backend {backend} ...\n")
    ada = []
    for i in range(sampai):
        k = cv2.VideoCapture(i, pilih_backend(backend))
        bisa = k.isOpened()
        ukuran = ""
        if bisa:
            berhasil, bingkai = k.read()
            if berhasil and bingkai is not None:
                ukuran = f"  {bingkai.shape[1]} x {bingkai.shape[0]}"
                ada.append(i)
            else:
                bisa = False
        k.release()
        print(f"  kamera {i} : {'BISA' if bisa else 'tidak'}{ukuran}")

    print()
    if ada:
        print(f"Coba jalankan dengan: --kamera {ada[0]}")
    return ada


def jarak(a, b, aspek):
    dx = (a.x - b.x) * aspek
    dy = a.y - b.y
    return (dx * dx + dy * dy) ** 0.5


def nilai_jari(titik, tip, pip, acuan, aspek):
    d_tip = jarak(titik[tip], titik[acuan], aspek)
    d_pip = jarak(titik[pip], titik[acuan], aspek)
    if d_pip < 1e-6:
        return False, 0.0

    rasio = d_tip / d_pip
    lurus = rasio > AMBANG_LURUS
    margin = min(abs(rasio - AMBANG_LURUS) / LEBAR_KEYAKINAN, 1.0)
    return lurus, margin


def baca_bentuk_tangan(titik, aspek):
    pola = []
    margin_terkecil = 1.0

    lurus, margin = nilai_jari(titik, JEMPOL_TIP, JEMPOL_IP, PANGKAL_KELINGKING, aspek)
    pola.append(lurus)
    margin_terkecil = min(margin_terkecil, margin)

    for _, tip, pip in EMPAT_JARI:
        lurus, margin = nilai_jari(titik, tip, pip, PERGELANGAN, aspek)
        pola.append(lurus)
        margin_terkecil = min(margin_terkecil, margin)

    return tuple(pola), margin_terkecil


class PenilaiGestur:
    def __init__(self, ambang_confidence=0.45, bingkai_masuk=4, bingkai_keluar=6):
        self.ambang_confidence = ambang_confidence
        self.bingkai_masuk = bingkai_masuk
        self.bingkai_keluar = bingkai_keluar

        self.gestur_diakui = "TIDAK_ADA"
        self._calon = "TIDAK_ADA"
        self._hitung_calon = 0
        self._hitung_hilang = 0

    def perbarui(self, gestur_mentah, confidence):
        if confidence < self.ambang_confidence:
            gestur_mentah = "TIDAK_ADA"

        if gestur_mentah == self.gestur_diakui:
            self._hitung_hilang = 0
            self._calon = gestur_mentah
            self._hitung_calon = self.bingkai_masuk
            return self.gestur_diakui, True

        if gestur_mentah == self._calon:
            self._hitung_calon += 1
        else:
            self._calon = gestur_mentah
            self._hitung_calon = 1

        if self._hitung_calon >= self.bingkai_masuk:
            self.gestur_diakui = self._calon
            self._hitung_hilang = 0
            return self.gestur_diakui, True

        self._hitung_hilang += 1
        if self._hitung_hilang >= self.bingkai_keluar:
            self.gestur_diakui = "TIDAK_ADA"

        return self.gestur_diakui, False

    @property
    def kemajuan(self):
        return min(self._hitung_calon / self.bingkai_masuk, 1.0)


def gambar_tangan(bingkai, titik):
    tinggi, lebar = bingkai.shape[:2]
    piksel = [(int(t.x * lebar), int(t.y * tinggi)) for t in titik]

    for garis in vision.HandLandmarksConnections.HAND_CONNECTIONS:
        cv2.line(bingkai, piksel[garis.start], piksel[garis.end], (160, 160, 160), 2)

    for i, (px, py) in enumerate(piksel):
        warna = (0, 209, 178) if i in (4, 8, 12, 16, 20) else (240, 160, 60)
        cv2.circle(bingkai, (px, py), 5, warna, -1)


def gambar_panel_multi(bingkai, info_panel, fps):
    """Jendela pengawasan yang mendukung tampilan hingga 2 tangan sekaligus."""
    tinggi, lebar = bingkai.shape[:2]
    cv2.rectangle(bingkai, (0, 0), (lebar, 96), (26, 20, 18), -1)

    cv2.putText(bingkai, f"{fps:.0f} FPS", (14, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (190, 190, 190), 1)

    if not info_panel:
        cv2.putText(bingkai, "TIDAK_ADA", (14, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 150, 240), 2)

    # Gambar data untuk masing-masing tangan (berjejer menyamping)
    for i, info in enumerate(info_panel):
        offset_x = i * 180  # Jarak antar kolom teks tangan
        
        warna = (178, 209, 0) if info["stabil"] and info["gestur"] != "TIDAK_ADA" else (80, 150, 240)
        inisial_tangan = info["tangan"][:1]  # 'L' atau 'R'
        cv2.putText(bingkai, f"{inisial_tangan}: {info['gestur']}", (14 + offset_x, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.8, warna, 2)
        cv2.putText(bingkai, f"m: {info['mentah']}", (14 + offset_x, 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (190, 190, 190), 1)
        cv2.putText(bingkai, f"c: {info['confidence']:.2f}", (14 + offset_x, 86),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (190, 190, 190), 1)

        # Batang keyakinan dan kestabilan
        lb = 130
        x_bar = max(lebar - 300 + (i * 140), 0)  # Menempel di kanan atas
        y0 = 24
        cv2.rectangle(bingkai, (x_bar, y0), (x_bar + lb, y0 + 10), (70, 70, 70), -1)
        cv2.rectangle(bingkai, (x_bar, y0), (x_bar + int(lb * info["confidence"]), y0 + 10), warna, -1)
        cv2.putText(bingkai, f"conf {inisial_tangan}", (x_bar, y0 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (190, 190, 190), 1)

        y1 = y0 + 26
        cv2.rectangle(bingkai, (x_bar, y1), (x_bar + lb, y1 + 10), (70, 70, 70), -1)
        cv2.rectangle(bingkai, (x_bar, y1), (x_bar + int(lb * info["kemajuan"]), y1 + 10), (178, 209, 0), -1)
        cv2.putText(bingkai, f"stab {inisial_tangan}", (x_bar, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (190, 190, 190), 1)

    cv2.putText(bingkai, "q untuk berhenti", (14, tinggi - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)


def main():
    p = argparse.ArgumentParser(description="Pelacak gestur tangan untuk Unity")
    p.add_argument("--kamera", type=int, default=0, help="nomor webcam, biasanya 0")
    p.add_argument("--host", default="127.0.0.1", help="alamat tujuan UDP")
    p.add_argument("--port", type=int, default=5005, help="porta tujuan UDP")
    p.add_argument("--ambang", type=float, default=0.33, help="ambang confidence")
    p.add_argument("--model", default=None, help="letak berkas hand_landmarker.task")
    p.add_argument("--backend", default="dshow" if os.name == "nt" else "auto",
                   choices=["auto", "dshow", "msmf", "v4l2"],
                   help="pembaca kamera. Di Windows, coba msmf bila dshow bermasalah")
    p.add_argument("--lebar", type=int, default=640, help="lebar bingkai kamera")
    p.add_argument("--tinggi", type=int, default=480, help="tinggi bingkai kamera")
    p.add_argument("--daftar-kamera", action="store_true",
                   help="tampilkan nomor kamera yang tersedia, lalu berhenti")
    p.add_argument("--tanpa-jendela", action="store_true", help="jangan tampilkan jendela kamera")
    argumen = p.parse_args()

    if argumen.daftar_kamera:
        daftar_kamera(argumen.backend)
        return

    path_model = argumen.model or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), NAMA_MODEL)
    if not siapkan_model(path_model):
        return

    pengirim = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tujuan = (argumen.host, argumen.port)

    kamera = buka_kamera(argumen.kamera, argumen.backend, argumen.lebar, argumen.tinggi)
    if kamera is None:
        print(f"Kamera nomor {argumen.kamera} tidak dapat dibuka dengan backend {argumen.backend}.")
        return

    # DIUBAH: num_hands menjadi 2
    opsi = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=path_model),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2, 
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    # DIUBAH: Dua penilai independen untuk Kiri dan Kanan
    penilai = {
        "Left": PenilaiGestur(ambang_confidence=argumen.ambang),
        "Right": PenilaiGestur(ambang_confidence=argumen.ambang)
    }
    
    mulai = time.time()
    ms_rerata = 33.0

    print(f"Mengirim ke {argumen.host}:{argumen.port}. "
          "Tekan q pada jendela kamera untuk berhenti.")

    with vision.HandLandmarker.create_from_options(opsi) as pelacak:

        while True:
            awal = time.time()
            berhasil, bingkai = kamera.read()
            if not berhasil:
                continue

            bingkai = cv2.flip(bingkai, 1)
            tinggi, lebar = bingkai.shape[:2]
            aspek = lebar / tinggi

            stempel_ms = int((time.time() - mulai) * 1000)

            gambar_mp = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(bingkai, cv2.COLOR_BGR2RGB))
            hasil = pelacak.detect_for_video(gambar_mp, stempel_ms)

            paket_tangan = []
            info_panel = []

            # DIUBAH: Loop memproses seluruh tangan yang terdeteksi
            if hasil.hand_landmarks:
                for i in range(len(hasil.hand_landmarks)):
                    titik = hasil.hand_landmarks[i]
                    kategori = hasil.handedness[i][0]

                    sisi_tangan = kategori.category_name
                    skor_model = kategori.score

                    titik_x = float(min(max(titik[TELUNJUK_TIP].x, 0.0), 1.0))
                    titik_y = float(min(max(titik[TELUNJUK_TIP].y, 0.0), 1.0))

                    pola, margin = baca_bentuk_tangan(titik, aspek)
                    gestur_mentah = POLA_GESTUR.get(pola, "TIDAK_DIKENAL")

                    confidence = margin * skor_model
                    if gestur_mentah == "TIDAK_DIKENAL":
                        confidence *= 0.4

                    if not argumen.tanpa_jendela:
                        gambar_tangan(bingkai, titik)

                    # Pemrosesan penilai berdasarkan sisi tangan
                    gestur, stabil = penilai[sisi_tangan].perbarui(gestur_mentah, confidence)

                    # Masukkan ke array payload untuk dikirim ke Unity
                    paket_tangan.append({
                        "gestur": gestur,
                        "confidence": round(confidence, 3),
                        "stabil": bool(stabil and gestur != "TIDAK_ADA"),
                        "tangan": sisi_tangan,
                        "x": round(titik_x, 4),
                        "y": round(titik_y, 4),
                    })

                    # Masukkan data ke array untuk digambar di UI OpenCV
                    info_panel.append({
                        "tangan": sisi_tangan,
                        "gestur": gestur,
                        "mentah": gestur_mentah,
                        "confidence": confidence,
                        "kemajuan": penilai[sisi_tangan].kemajuan,
                        "stabil": stabil
                    })

            # DIUBAH: Struktur data sekarang mengelompokkan payload dalam "data"
            payload = {
                "waktu": round(time.time() - mulai, 3),
                "data": paket_tangan
            }
            pengirim.sendto(json.dumps(payload).encode("utf-8"), tujuan)

            ms = (time.time() - awal) * 1000.0
            ms_rerata += (ms - ms_rerata) * 0.1

            if not argumen.tanpa_jendela:
                gambar_panel_multi(bingkai, info_panel, 1000.0 / max(ms_rerata, 0.1))
                cv2.imshow("Pelacak Gestur - RVRA P11", bingkai)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    kamera.release()
    cv2.destroyAllWindows()
    pengirim.close()
    print("Selesai.")


if __name__ == "__main__":
    main()