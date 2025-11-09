# PST Analysis Engine

## Overview
The PST Analysis Engine is a powerful tool designed for processing and analyzing PST files. It extracts data, processes emails, and facilitates migration to various formats and storage systems.

## Project Structure
```
pst-analysis-engine
├── src
│   ├── __main__.py
│   ├── core
│   │   ├── pst_reader.py
│   │   ├── pst_parser.py
│   │   └── email_processor.py
│   ├── migration
│   │   ├── migration_engine.py
│   │   └── adapters
│   │       ├── exchange_adapter.py
│   │       └── imap_adapter.py
│   ├── processing
│   │   ├── attachment_extractor.py
│   │   ├── metadata_extractor.py
│   │   └── content_analyzer.py
│   ├── storage
│   │   ├── storage_manager.py
│   │   └── sqlite_backend.py
│   └── utils
│       ├── logger.py
│       └── validators.py
├── tests
│   ├── unit
│   │   ├── test_pst_reader.py
│   │   └── test_email_processor.py
│   └── integration
│       └── test_migration_flow.py
├── configs
│   └── default.yaml
├── pyproject.toml
├── requirements.txt
├── setup.cfg
├── LICENSE
└── README.md
```

## Installation
1. Clone the repository:
   ```
   git clone <repository-url>
   ```
2. Navigate to the project directory:
   ```
   cd pst-analysis-engine
   ```
3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage
To run the analysis engine, execute the following command:
```
python -m src
```

## Contributing
Contributions are welcome! Please submit a pull request or open an issue for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for details.