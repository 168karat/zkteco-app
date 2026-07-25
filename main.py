from fastapi import FastAPI, Request, Depends, Form, HTTPException, status, File, UploadFile, Query
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, date, time
import json
import os
import shutil

from database import Base, engine, SessionLocal, Employee, Attendance, Device

app = FastAPI(title="ZKTeco ADMS Server")

# Create directories if not exists
os.makedirs("templates", exist_ok=True)
os.makedirs("static/avatars", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Global command queue for the device
pending_commands = []

# --- ADMS Endpoints ---

@app.get("/iclock/cdata")
@app.get("/iclock/cdata.aspx")
@app.get("/iclock/registry")
def cdata_get(SN: str = None, options: str = None, db: Session = Depends(get_db)):
    if SN:
        device = db.query(Device).filter(Device.sn == SN).first()
        if not device:
            device = Device(sn=SN)
            db.add(device)
            db.commit()
    return PlainTextResponse("OK")

@app.get("/iclock/getrequest")
@app.get("/iclock/getrequest.aspx")
@app.get("/iclock/fdata")
def getrequest(SN: str = None, db: Session = Depends(get_db)):
    if SN:
        device = db.query(Device).filter(Device.sn == SN).first()
        if device:
            device.last_active = datetime.utcnow()
            db.commit()
            
    if pending_commands:
        cmd = pending_commands.pop(0)
        return PlainTextResponse(cmd)
        
    return PlainTextResponse("OK")

@app.post("/iclock/cdata")
@app.post("/iclock/cdata.aspx")
@app.post("/iclock/fdata")
async def cdata_post(request: Request, SN: str = None, table: str = None, Stamp: str = None, db: Session = Depends(get_db)):
    try:
        body = await request.body()
        print(f"[DEBUG ADMS POST] table={table}, SN={SN}, body={body.decode('utf-8', errors='ignore')[:200]}")
        lines = body.decode('utf-8', errors='ignore').strip().split('\n')
        
        if SN:
            device = db.query(Device).filter(Device.sn == SN).first()
            if not device:
                device = Device(sn=SN)
                db.add(device)
            device.last_active = datetime.utcnow()
            db.commit()
                
        if table == "ATTLOG":
            for line in lines:
                if not line.strip():
                    continue
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    pin = parts[0].strip()
                    time_str = parts[1].strip()
                    
                    try:
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                    # Deduplication Check
                    existing = db.query(Attendance).filter(
                        Attendance.employee_pin == pin,
                        Attendance.timestamp == dt
                    ).first()
                    
                    if existing:
                        continue

                    employee = db.query(Employee).filter(Employee.pin == pin).first()
                    if not employee:
                        employee = Employee(pin=pin, name=f"Unknown-{pin}")
                        db.add(employee)
                        db.commit()
                        db.refresh(employee)
                    
                    verify_mode = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                    in_out = get_in_out_status(db, pin, dt)
                    
                    att = Attendance(
                        employee_pin=pin,
                        timestamp=dt,
                        verify_mode=verify_mode,
                        in_out_state=in_out
                    )
                    db.add(att)
                    db.commit()
                        
        elif table in ["USERINFO", "USER", "OPERLOG", "BIODATA", "BIOPHOTO"]:
            for line in lines:
                if not line.strip():
                    continue
                parts = line.strip().split('\t')
                user_dict = {}
                for part in parts:
                    if '=' in part:
                        k, v = part.split('=', 1)
                        user_dict[k.strip()] = v.strip()
                        
                pin = None
                name = ""
                
                if 'PIN' in user_dict:
                    pin = user_dict['PIN']
                    name = user_dict.get('Name', '')
                elif 'Pin' in user_dict:
                    pin = user_dict['Pin']
                    name = user_dict.get('Name', '')
                elif len(parts) >= 1 and parts[0].isdigit():
                    pin = parts[0].strip()
                    if len(parts) >= 2 and not '=' in parts[1]:
                        name = parts[1].strip()

                if pin:
                    if not name:
                        name = f"Unknown-{pin}"
                        
                    employee = db.query(Employee).filter(Employee.pin == pin).first()
                    if employee:
                        if employee.name.startswith("Unknown-") and name and not name.startswith("Unknown-"):
                            employee.name = name
                    else:
                        employee = Employee(pin=pin, name=name)
                        db.add(employee)
                    db.commit()
    except Exception as e:
        print(f"[ADMS Error] Exception in cdata_post: {e}")
            
    return PlainTextResponse("OK")

@app.post("/iclock/devicecmd")
@app.post("/iclock/devicecmd.aspx")
async def devicecmd(request: Request):
    return PlainTextResponse("OK")

@app.api_route("/iclock/{path:path}", methods=["GET", "POST"])
async def iclock_fallback(path: str, request: Request):
    print(f"[ADMS Fallback] Method: {request.method}, Path: {path}, Query: {request.query_params}")
    return PlainTextResponse("OK")

# --- Dashboard Endpoints ---

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    attendances = db.query(Attendance).order_by(Attendance.timestamp.desc()).limit(50).all()
    employees = db.query(Employee).all()
    devices = db.query(Device).all()
    for a in attendances:
        a.computed_status = get_in_out_status(db, a.employee_pin, a.timestamp)
    return templates.TemplateResponse(request=request, name="index.html", context={"attendances": attendances, "employees": employees, "devices": devices})

def get_in_out_status(db: Session, pin: str, ts: datetime) -> int:
    day_start = datetime.combine(ts.date(), time.min)
    scan_count = db.query(Attendance).filter(
        Attendance.employee_pin == pin,
        Attendance.timestamp >= day_start,
        Attendance.timestamp <= ts
    ).count()
    
    if scan_count <= 1:
        # First scan of the day
        if ts.time() > time(8, 30, 0):
            return 2  # เข้างานสาย (Yellow)
        else:
            return 0  # เข้างานแล้ว (Green)
    else:
        # Second or later scan of the day
        return 1  # เลิกงานแล้ว (Red)

@app.get("/api/live_data")
def live_data(db: Session = Depends(get_db)):
    attendances = db.query(Attendance).order_by(Attendance.timestamp.desc()).limit(50).all()
    total_employees = db.query(Employee).count()
    
    # Scanned today unique count
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_attendances = db.query(Attendance.employee_pin).filter(Attendance.timestamp >= today_start).distinct().all()
    scanned_today_count = len(today_attendances)
    
    scan_percent = int((scanned_today_count / total_employees * 100)) if total_employees > 0 else 0
    
    device = db.query(Device).first()
    is_online = False
    last_active_str = "-"
    if device and device.last_active:
        diff_seconds = (datetime.utcnow() - device.last_active).total_seconds()
        is_online = diff_seconds < 1800 # online if pinged within 30 mins (accounting for idle polling)
        last_active_str = device.last_active.strftime("%H:%M:%S %d/%m/%Y")

    att_list = []
    for a in attendances:
        emp_name = a.employee.name if a.employee else f"ไม่พบข้อมูล ({a.employee_pin})"
        avatar_url = a.employee.avatar_url if (a.employee and a.employee.avatar_url) else ""
        computed_in_out = get_in_out_status(db, a.employee_pin, a.timestamp)
        att_list.append({
            "pin": a.employee_pin,
            "name": emp_name,
            "avatar_url": avatar_url,
            "time": a.timestamp.strftime("%H:%M:%S %d/%m/%Y"),
            "in_out": computed_in_out,
            "verify_mode": a.verify_mode
        })
        
    return JSONResponse({
        "stats": {
            "total_employees": total_employees,
            "scanned_today": scanned_today_count,
            "scan_percent": scan_percent,
            "is_online": is_online,
            "last_active": last_active_str
        },
        "attendances": att_list
    })

@app.get("/employees", response_class=HTMLResponse)
def employee_management(request: Request, db: Session = Depends(get_db)):
    employees = db.query(Employee).all()
    return templates.TemplateResponse(request=request, name="users.html", context={"employees": employees})

@app.post("/api/sync_users")
def sync_users():
    pending_commands.append("C:1:DATA QUERY USERINFO")
    pending_commands.append("C:2:DATA QUERY ATTLOG")
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/employees/update")
async def update_employee(
    request: Request, 
    pin: str = Form(...), 
    name: str = Form(...), 
    department: str = Form(...), 
    role: str = Form(...), 
    avatar: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    employee = db.query(Employee).filter(Employee.pin == pin).first()
    
    avatar_path = None
    if avatar and avatar.filename:
        file_extension = os.path.splitext(avatar.filename)[1]
        new_filename = f"avatar_{pin}{file_extension}"
        save_path = os.path.join("static", "avatars", new_filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(avatar.file, buffer)
        avatar_path = f"/static/avatars/{new_filename}"

    if employee:
        employee.name = name
        employee.department = department
        employee.role = role
        if avatar_path:
            employee.avatar_url = avatar_path
    else:
        new_emp = Employee(pin=pin, name=name, department=department, role=role, avatar_url=avatar_path)
        db.add(new_emp)
    db.commit()
    
    # Queue ADMS command to push this user name to the physical scanner machine
    cmd_role = "14" if role == "admin" else "0"
    pending_commands.append(f"C:10:DATA UPDATE USERINFO PIN={pin}\tName={name}\tPri={cmd_role}")
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/push_users_to_device")
def push_users_to_device(db: Session = Depends(get_db)):
    employees = db.query(Employee).all()
    for idx, emp in enumerate(employees):
        cmd_role = "14" if emp.role == "admin" else "0"
        pending_commands.append(f"C:{idx+100}:DATA UPDATE USERINFO PIN={emp.pin}\tName={emp.name}\tPri={cmd_role}")
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/employees/delete/{pin}")
def delete_employee(pin: str, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.pin == pin).first()
    if employee:
        if employee.avatar_url:
            local_file = employee.avatar_url.lstrip("/")
            if os.path.exists(local_file):
                try:
                    os.remove(local_file)
                except Exception:
                    pass
        db.delete(employee)
        db.commit()
        # Also queue command to delete user from device
        pending_commands.append(f"C:1:DATA DELETE USERINFO PIN={pin}")
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)

import io
import csv
from fastapi.responses import StreamingResponse

@app.get("/export/excel")
def export_excel(start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    query = db.query(Attendance)
    if start_date:
        query = query.filter(Attendance.timestamp >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        query = query.filter(Attendance.timestamp <= datetime.strptime(end_date, "%Y-%m-%d 23:59:59"))
        
    records = query.order_by(Attendance.timestamp.desc()).all()

    output = io.StringIO()
    output.write('\ufeff') # UTF-8 BOM for Microsoft Excel Thai language compatibility
    writer = csv.writer(output)
    writer.writerow(["รหัสพนักงาน", "ชื่อ-นามสกุล", "แผนก", "วัน-เวลาที่สแกน", "สถานะ", "รูปแบบสแกน"])

    for r in records:
        emp_name = r.employee.name if r.employee else f"ไม่พบข้อมูล ({r.employee_pin})"
        dept = r.employee.department if r.employee else "-"
        computed_status = get_in_out_status(db, r.employee_pin, r.timestamp)
        if computed_status == 0:
            in_out = "เข้างานแล้ว"
        elif computed_status == 2:
            in_out = "เข้างานสาย"
        else:
            in_out = "เลิกงานแล้ว"
        verify = "สแกนใบหน้า" if r.verify_mode == 15 else ("สแกนนิ้ว" if r.verify_mode == 1 else str(r.verify_mode))
        
        writer.writerow([r.employee_pin, emp_name, dept, r.timestamp.strftime("%H:%M:%S %d/%m/%Y"), in_out, verify])

    output.seek(0)
    filename = f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8-sig", headers=headers)

@app.get("/api/reports")
def get_reports(start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    query = db.query(Attendance)
    if start_date:
        query = query.filter(Attendance.timestamp >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        query = query.filter(Attendance.timestamp <= datetime.strptime(end_date, "%Y-%m-%d 23:59:59"))
        
    records = query.order_by(Attendance.timestamp.desc()).all()
    return [{"pin": r.employee_pin, "name": r.employee.name if r.employee else "N/A", "time": r.timestamp.strftime("%H:%M:%S %d/%m/%Y")} for r in records]

@app.get("/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    start_date: str = Query(None),
    end_date: str = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Attendance)
    if start_date:
        try:
            dt_start = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(Attendance.timestamp >= dt_start)
        except ValueError:
            pass
    if end_date:
        try:
            dt_end = datetime.strptime(end_date, "%Y-%m-%d 23:59:59")
            query = query.filter(Attendance.timestamp <= dt_end)
        except ValueError:
            pass
            
    records = query.order_by(Attendance.timestamp.desc()).all()
    for r in records:
        r.computed_status = get_in_out_status(db, r.employee_pin, r.timestamp)
        
    return templates.TemplateResponse(
        request=request,
        name="reports.html",
        context={
            "attendances": records,
            "start_date": start_date or "",
            "end_date": end_date or ""
        }
    )
