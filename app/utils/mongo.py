def fix_mongo_types(doc):
    from bson import ObjectId
    from datetime import datetime
    from app.utils.get_time import utc_to_ist

    if isinstance(doc, dict):
        return {k: fix_mongo_types(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [fix_mongo_types(i) for i in doc]
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, datetime):
        doc = utc_to_ist(doc)
        return doc.isoformat()  # Convert datetime to ISO string
    else:
        return doc