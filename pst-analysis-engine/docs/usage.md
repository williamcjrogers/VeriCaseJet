# Usage Instructions for PST Analysis Engine

## Overview
The PST Analysis Engine is designed to process PST files, extracting and analyzing email data efficiently. This document provides guidance on how to use the software effectively.

## Installation
1. Clone the repository:
   ```
   git clone <repository-url>
   cd pst-analysis-engine
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage
To run the analysis engine, execute the following command in your terminal:

```
python -m src
```

### Command-Line Options
- `--input <path>`: Specify the path to the PST file you want to analyze.
- `--output <path>`: Specify the output directory for the extracted data.
- `--format <type>`: Choose the output format (e.g., JSON, CSV).

### Example
To analyze a PST file and output the results in JSON format, use the following command:

```
python -m src --input /path/to/file.pst --output /path/to/output --format json
```

## Features
- **PST File Reading**: Efficiently reads PST files and extracts email data.
- **Data Parsing**: Parses extracted data into a structured format for easy analysis.
- **Email Processing**: Processes email data, including attachments and metadata extraction.
- **Migration Support**: Facilitates migration of data to various formats and storage systems.

## Contributing
Contributions are welcome! Please submit a pull request or open an issue for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.