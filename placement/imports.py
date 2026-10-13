import csv
import io
import zipfile
from django.core.exceptions import ValidationError
from openpyxl import load_workbook
from .forms import StudentForm
from .models import Student

COLUMNS = ['placement_id','name','email','mobile','course','batch','registration','eligibility','academic_score']

def parse_upload(upload, user):
    if upload.size > 2*1024*1024: raise ValidationError('File must be smaller than 2 MB.')
    raw = upload.read()
    if upload.name.lower().endswith('.csv'):
        try:
            rows = []
            for row in csv.reader(io.StringIO(raw.decode('utf-8-sig'))):
                if len(rows)>=501: raise ValidationError('Maximum 500 records per import.')
                rows.append(row)
        except (UnicodeError,csv.Error): raise ValidationError('Upload a valid UTF-8 CSV file.')
    elif upload.name.lower().endswith('.xlsx'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(item.file_size for item in archive.infolist())>10*1024*1024 or len(archive.infolist())>100:
                    raise ValidationError('Workbook decompression limits exceeded.')
            workbook = load_workbook(io.BytesIO(raw),read_only=True,data_only=False,keep_links=False)
            if len(workbook.sheetnames)!=1: raise ValidationError('Use a single-sheet workbook.')
            rows = []
            for row in workbook.active.iter_rows():
                if len(rows)>500: raise ValidationError('Maximum 500 records per import.')
                if len(row)>len(COLUMNS): raise ValidationError('Unexpected workbook columns.')
                if any(cell.data_type=='f' for cell in row): raise ValidationError('Formula cells are not accepted.')
                rows.append([str(cell.value) if cell.value is not None else '' for cell in row])
            workbook.close()
        except ValidationError: raise
        except Exception as exc: raise ValidationError('Invalid or unsupported workbook.') from exc
    else: raise ValidationError('Only CSV and XLSX are supported.')
    if not rows or rows[0]!=COLUMNS: raise ValidationError('Columns must match the provided import template exactly.')
    if len(rows)>501: raise ValidationError('Maximum 500 records per import.')
    valid, errors, seen = [], [], set()
    for index,row in enumerate(rows[1:],start=2):
        if len(row)!=len(COLUMNS): errors.append(f'Row {index}: incorrect column count.'); continue
        data = dict(zip(COLUMNS,row))
        if any(len(value)>200 for value in row): errors.append(f'Row {index}: a field exceeds 200 characters.'); continue
        form = StudentForm(data)
        if not form.is_valid(): errors.append(f'Row {index}: {form.errors.as_text()}'); continue
        if data['placement_id'] in seen: errors.append(f'Row {index}: duplicate Placement ID.'); continue
        if user.role=='coordinator' and data['course'] not in user.courses:
            errors.append(f'Row {index}: course outside your authorization.'); continue
        seen.add(data['placement_id'])
        valid.append(data)
    return valid, errors

def safe_cell(value):
    value = str(value if value is not None else '')
    # Leading whitespace/control characters can hide spreadsheet formula prefixes.
    return "'"+value if value.lstrip(' \t\r\n').startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value
