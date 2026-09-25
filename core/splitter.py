from pypdf import PdfReader, PdfWriter
from typing import Set, List, Callable, Optional

def parse_range_string(range_str: str, max_pages: int) -> List[int]:
    
    selected_indices: Set[int] = set()
    parts = [p.strip() for p in range_str.split(",") if p.strip()]
    
    if not parts:
        raise ValueError("El campo de rangos no puede estar vacío.")
    
    for part in parts:
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
                raise ValueError(f"Rango inválido: {part}")
            start, end = int(bounds[0]), int(bounds[1])
            if start > end:
                raise ValueError(f"Rango invertido: {part}")
            for page_num in range(start, end + 1):
                if 1 <= page_num <= max_pages:
                    selected_indices.add(page_num - 1)
                else:
                    raise ValueError(f"Página {page_num} fuera de rango (1 - {max_pages}).")
        else:
            if not part.isdigit():
                raise ValueError(f"Valor no numérico detectado: {part}")
            page_num = int(part)
            if 1 <= page_num <= max_pages:
                selected_indices.add(page_num - 1)
            else:
                raise ValueError(f"Página {page_num} fuera de rango (1 - {max_pages})")
            
    result = sorted(list(selected_indices))
    if not result:
        raise ValueError("No se seleccionaron páginas válidas.")
    return result

def split_pdf_pages(
    input_path: str,
    output_path: str,
    range_str: str,
    progress_callback: Optional[Callable[[int], None]] = None
) -> None:
    reader = PdfReader(input_path)
    total_pages = len(reader.pages)
    target_indices = parse_range_string(range_str, total_pages)
    
    writer =  PdfWriter()
    
    total_to_extract = len(target_indices)
    
    for step, idx in enumerate(target_indices, start=1):
        writer.add_page(reader.pages[idx])
        if progress_callback:
            progress_callback(int((step / total_to_extract) * 90))
            
    with open(output_path, "wb") as f_out:
        writer.write(f_out)
        
    if progress_callback:
        progress_callback(100)