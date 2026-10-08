"""Scrollable record table with real cell borders and fixed column headings."""
import tkinter as tk
from tkinter import font as tkfont


class RecordGrid(tk.Frame):
    def __init__(self, master, columns, **kwargs):
        super().__init__(master, bg='#8998aa', bd=1)
        self.columns = list(columns)
        self.widths = {key:110 for key in self.columns}
        self.titles = {key:key for key in self.columns}
        self.rows = []
        self.row_height = 34
        self.font = tkfont.Font(family='Microsoft YaHei UI', size=10)
        self.header = tk.Canvas(self, height=36, bg='#e8edf5', highlightthickness=0)
        self.body = tk.Canvas(self, bg='white', highlightthickness=0)
        self.header.pack(fill='x')
        self.body.pack(fill='both', expand=True)
        self.body.bind('<MouseWheel>', lambda event:self.body.yview_scroll(-int(event.delta/120),'units'))
        self.body.configure(yscrollincrement=self.row_height)
        self.body.bind('<Button-1>', self.select_row)
        self.selected = None

    def fit_text(self, value, width):
        text = str(value)
        if self.font.measure(text) <= width:
            return text
        low,high = 0,len(text)
        while low < high:
            middle=(low+high+1)//2
            if self.font.measure(text[:middle]+'…') <= width:
                low=middle
            else:
                high=middle-1
        return text[:low]+'…'

    def heading(self, key, text):
        self.titles[key]=text
        self.draw_header()

    def column(self, key, width=None, **kwargs):
        if width is not None:
            self.widths[key]=width
            self.redraw()

    def draw_header(self):
        self.header.delete('all')
        x=0
        for key in self.columns:
            width=self.widths[key]
            self.header.create_rectangle(x,0,x+width,36,fill='#e8edf5',outline='#8998aa',width=1)
            self.header.create_text(x+width/2,18,text=self.fit_text(self.titles[key],width-12),font=self.font,fill='#172b43')
            x+=width
        self.header.configure(scrollregion=(0,0,x,36))

    def draw_row(self, index):
        values=self.rows[index]
        y=index*self.row_height
        x=0
        color='#dbeaff' if index==self.selected else ('#f2f6fb' if index%2 else 'white')
        for column,key in enumerate(self.columns):
            width=self.widths[key]
            self.body.create_rectangle(x,y,x+width,y+self.row_height,fill=color,outline='#a8b3c2',width=1,tags=f'row{index}')
            value=values[column] if column<len(values) else ''
            self.body.create_text(x+7,y+self.row_height/2,text=self.fit_text(value,width-14),anchor='w',font=self.font,fill='#172b43',tags=f'row{index}')
            x+=width
        self.body.configure(scrollregion=(0,0,x,max(self.row_height,len(self.rows)*self.row_height)))

    def redraw(self):
        self.draw_header()
        self.body.delete('all')
        for index in range(len(self.rows)):
            self.draw_row(index)

    def insert(self, parent, position, values):
        self.rows.append(tuple(values))
        index=len(self.rows)-1
        self.draw_row(index)
        return str(index)

    def get_children(self):
        return tuple(str(index) for index in range(len(self.rows)))

    def delete(self, *items):
        if not items:
            return
        for index in sorted((int(item) for item in items),reverse=True):
            self.rows.pop(index)
        self.selected=None
        self.redraw()
        self.body.configure(scrollregion=(0,0,sum(self.widths.values()),max(self.row_height,len(self.rows)*self.row_height)))

    def configure(self, **kwargs):
        scroll={key:kwargs.pop(key) for key in ('yscrollcommand','xscrollcommand') if key in kwargs}
        if scroll:
            self.body.configure(**scroll)
        if kwargs:
            super().configure(**kwargs)

    def yview(self, *args):
        return self.body.yview(*args)

    def xview(self, *args):
        value=self.body.xview(*args)
        self.header.xview_moveto(self.body.xview()[0])
        return value

    def see(self, item):
        row=int(item)
        top=self.body.canvasy(0)
        bottom=top+self.body.winfo_height()
        start=row*self.row_height
        if start < top or start+self.row_height > bottom:
            total=max(self.row_height,len(self.rows)*self.row_height)
            self.body.yview_moveto(max(0,start+self.row_height-self.body.winfo_height())/total)

    def identify_row(self, y):
        row=int(self.body.canvasy(y)//self.row_height)
        return str(row) if 0<=row<len(self.rows) else ''

    def index(self, item):
        return int(item)

    def bind(self, sequence=None, func=None, add=None):
        return self.body.bind(sequence,func,add)

    def select_row(self,event):
        item=self.identify_row(event.y)
        previous=self.selected
        self.selected=int(item) if item else None
        for index in {previous,self.selected}:
            if index is not None:
                self.body.delete(f'row{index}')
                self.draw_row(index)
