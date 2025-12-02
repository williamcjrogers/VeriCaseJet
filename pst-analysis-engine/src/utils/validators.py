def validate_email(email):
    import re

    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def validate_attachment_size(size, max_size):
    return size <= max_size


def validate_pst_file_format(file_path):
    return file_path.endswith(".pst")


def validate_metadata(metadata):
    required_fields = ["subject", "from", "to", "date"]
    return all(field in metadata for field in required_fields)
