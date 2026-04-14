# ReviewPro Pipeline

Aplicação para processamento diário de check-outs e geração de ficheiros para ReviewPro.

## Instalação

```bash
# 1. Criar ambiente virtual (recomendado)
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Iniciar a aplicação
streamlit run app.py
```

A aplicação abre automaticamente em http://localhost:8501

## Uso diário

1. **Importar ficheiros** — carrega Master, VTRL das 14h e GIR
2. Clica **Processar lote**
3. Revê matches prováveis em **Revisão de matches**
4. Em **Revisão operacional**, as guest relations adicionam notas e alteram estados
5. **Exportar** — descarrega Excel final, CSV e ficheiro ReviewPro

## Estrutura de ficheiros

```
reviewpro_pipeline/
├── app.py                  # Entrada principal Streamlit
├── requirements.txt
├── config/
│   └── settings.py         # Mapeamento, regras, palavras-chave
├── modules/
│   ├── loader.py           # Leitura de ficheiros
│   ├── mapper.py           # Mapeamento VTRL → master
│   ├── matcher.py          # Cruzamento com GIR
│   └── exporter.py         # Geração de outputs
├── history/                # Logs JSON de execuções
└── outputs/                # (opcional) outputs guardados localmente
```

## Configuração

Edita `config/settings.py` para:
- Ajustar aliases de colunas do VTRL
- Adicionar palavras-chave de exclusão/suspensão
- Alterar thresholds de matching fuzzy

## Automação diária (fase seguinte)

Para monitorizar uma pasta e processar automaticamente:

```python
# scheduler.py (exemplo com watchdog)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class VTRLHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.src_path.endswith(('.xlsx', '.csv')):
            # Processar VTRL automaticamente
            pass
```

Alternativas: Task Scheduler (Windows), cron (Linux/macOS), ou integração com OneDrive/SharePoint via Microsoft Graph API.
