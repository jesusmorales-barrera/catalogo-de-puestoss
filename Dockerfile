FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1         PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
        && apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation fonts-dejavu-core \
        && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY generar_catalogo.py /app/generar_catalogo.py
COPY editor_catalogo /app/editor_catalogo
COPY ssh_logo_recortado.png /app/ssh_logo_recortado.png

# La imagen 2.8 incluye generación PDF desde el editor web.
RUN grep -q 'add_section_bar(doc, "REQUISITOS")' /app/generar_catalogo.py \
        && grep -q 'set_record_header' /app/generar_catalogo.py \
        && grep -q 'Inches(3.05)' /app/generar_catalogo.py \
        && grep -q 'inline_roman_start' /app/generar_catalogo.py \
        && grep -q 'DENOMINACIÓN GENÉRICA DEL PUESTO' /app/generar_catalogo.py \
        && grep -q 'PERFIL DEL PUESTO' /app/generar_catalogo.py \
        && grep -q '"FUNCIONES"' /app/generar_catalogo.py \
        && grep -q 'set_table_widths' /app/generar_catalogo.py \
        && grep -q '"DENOMINACION GENERICA DEL PUESTO"' /app/generar_catalogo.py \
        && grep -q 'def load_records_json' /app/generar_catalogo.py \
        && grep -q 'class CatalogStore' /app/editor_catalogo/editor_catalogo.py

RUN useradd --create-home --uid 10001 appuser         && mkdir -p /salida         && chown -R appuser:appuser /app /salida

USER appuser

ENTRYPOINT ["python", "/app/generar_catalogo.py"]
CMD ["/datos/puestos_unificados.json", "--logo", "/app/ssh_logo_recortado.png", "--salida", "/salida/catalogo_puestos.docx"]
