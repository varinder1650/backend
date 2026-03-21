def fix_mongo_types(doc):
    from bson import ObjectId
    from datetime import datetime

    if isinstance(doc, dict):
        return {k: fix_mongo_types(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [fix_mongo_types(i) for i in doc]
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, datetime):
        # Always output as UTC ISO string with Z suffix
        # Frontend will convert to the user's local timezone
        iso = doc.isoformat()
        if not iso.endswith("Z") and "+" not in iso:
            iso += "Z"
        return iso
    else:
        return doc