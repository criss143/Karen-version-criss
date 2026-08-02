# Descarga y carga el modelo de audición para que esté listo al usar
from faster_whisper import WhisperModel

modelo = WhisperModel("small", device="cpu", compute_type="int8")
print("MODELO_STT_LISTO")
