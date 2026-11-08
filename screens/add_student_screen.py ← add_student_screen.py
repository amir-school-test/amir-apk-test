import logging

from kivy.app import App
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout


class AddStudentScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # ==========================================================
        # MAIN LAYOUT
        # ==========================================================

        main_layout = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=10
        )

        # ==========================================================
        # TITLE
        # ==========================================================

        title = Label(
            text="Manage Students",
            font_size="21sp",
            bold=True,
            color=(1, 0.85, 0.6, 1),
            size_hint_y=None,
            height=50
        )

        main_layout.add_widget(title)

        # ==========================================================
        # INPUT SECTION
        # ==========================================================

        input_layout = BoxLayout(
            orientation="vertical",
            spacing=8,
            size_hint_y=None,
            height=250
        )

        # ----------------------------------------------------------
        # STUDENT ID
        # ----------------------------------------------------------

        self.student_id_input = TextInput(
            hint_text="Student ID",
            multiline=False,
            font_size="16sp",
            size_hint_y=None,
            height=45
        )

        # ----------------------------------------------------------
        # NAME
        # ----------------------------------------------------------

        self.name_input = TextInput(
            hint_text="Full Name",
            multiline=False,
            font_size="16sp",
            size_hint_y=None,
            height=45
        )

        # ----------------------------------------------------------
        # GRADE
        # ----------------------------------------------------------

        self.grade_input = TextInput(
            hint_text="Grade (e.g. 12)",
            multiline=False,
            input_filter="int",
            font_size="16sp",
            size_hint_y=None,
            height=45
        )

        # ----------------------------------------------------------
        # SECTION
        # ----------------------------------------------------------

        self.section_input = TextInput(
            hint_text="Section (e.g. A)",
            multiline=False,
            font_size="16sp",
            size_hint_y=None,
            height=45
        )

        # ----------------------------------------------------------
        # PHONE
        # ----------------------------------------------------------

        self.phone_input = TextInput(
            hint_text="Guardian Phone Number (10 digits)",
            multiline=False,
            input_filter="int",
            font_size="16sp",
            size_hint_y=None,
            height=45
        )

        input_layout.add_widget(
            self.student_id_input
        )

        input_layout.add_widget(
            self.name_input
        )

        input_layout.add_widget(
            self.grade_input
        )

        input_layout.add_widget(
            self.section_input
        )

        input_layout.add_widget(
            self.phone_input
        )

        main_layout.add_widget(
            input_layout
        )

        # ==========================================================
        # ACTION BUTTONS
        # ==========================================================

        buttons = BoxLayout(
            orientation="horizontal",
            spacing=8,
            size_hint_y=None,
            height=50
        )

        add_button = Button(
            text="Add Student",
            background_normal="",
            background_color=(0.15, 0.65, 0.35, 1),
            bold=True
        )

        add_button.bind(
            on_press=self.add_student
        )

        update_button = Button(
            text="Update",
            background_normal="",
            background_color=(0.2, 0.5, 0.8, 1),
            bold=True
        )

        update_button.bind(
            on_press=self.update_student
        )

        delete_button = Button(
            text="Delete",
            background_normal="",
            background_color=(0.75, 0.25, 0.25, 1),
            bold=True
        )

        delete_button.bind(
            on_press=self.confirm_delete
        )

        buttons.add_widget(add_button)
        buttons.add_widget(update_button)
        buttons.add_widget(delete_button)

        main_layout.add_widget(
            buttons
        )

        # ==========================================================
        # STATUS
        # ==========================================================

        self.status_label = Label(
            text="",
            font_size="14sp",
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=45
        )

        self.status_label.bind(
            size=self.status_label.setter(
                "text_size"
            )
        )

        main_layout.add_widget(
            self.status_label
        )

        # ==========================================================
        # LIST TITLE
        # ==========================================================

        list_title = Label(
            text="Registered Students — Tap a student to edit",
            font_size="14sp",
            bold=True,
            color=(0.7, 0.8, 0.9, 1),
            size_hint_y=None,
            height=35
        )

        main_layout.add_widget(
            list_title
        )

        # ==========================================================
        # STUDENT LIST
        # ==========================================================

        self.scroll_view = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False,
            do_scroll_y=True
        )

        self.student_grid = GridLayout(
            cols=1,
            spacing=5,
            size_hint_y=None
        )

        self.student_grid.bind(
            minimum_height=self.student_grid.setter(
                "height"
            )
        )

        self.scroll_view.add_widget(
            self.student_grid
        )

        main_layout.add_widget(
            self.scroll_view
        )

        # ==========================================================
        # BACK BUTTON
        # ==========================================================

        back_button = Button(
            text="Back to Reports",
            size_hint_y=None,
            height=50,
            background_normal="",
            background_color=(0.5, 0.5, 0.5, 1),
            bold=True
        )

        back_button.bind(
            on_press=self.go_back
        )

        main_layout.add_widget(
            back_button
        )

        self.add_widget(
            main_layout
        )

    # ==============================================================
    # SCREEN ENTER
    # ==============================================================

    def on_enter(self):

        if not self._is_admin_authenticated():
            self._go_to_login()
            return

        self.clear_fields()
        self.clear_status()
        self.load_student_list()

    # ==============================================================
    # AUTHENTICATION
    # ==============================================================

    def _is_admin_authenticated(self):

        try:

            app = App.get_running_app()

            return bool(
                getattr(
                    app,
                    "admin_authenticated",
                    False
                )
            )

        except Exception as e:

            logging.error(
                f"Student screen authentication error: {e}"
            )

            return False

    def _go_to_login(self):

        if self.manager:
            self.manager.current = "admin_login"

    # ==============================================================
    # LOAD STUDENT LIST
    # ==============================================================

    def load_student_list(self):

        self.student_grid.clear_widgets()

        try:

            from database.students import (
                load_students_database
            )

            rows = load_students_database()

            if not rows:
                self._add_empty_message()
                return

            grouped_students = {}

            # New database format:
            #
            # (
            #     student_id,
            #     phone,
            #     name,
            #     grade,
            #     section
            # )

            for row in rows:

                if len(row) < 5:
                    continue

                student_id = str(
                    row[0]
                    if row[0] is not None
                    else ""
                ).strip()

                phone = str(
                    row[1]
                    if row[1] is not None
                    else ""
                ).strip()

                name = str(
                    row[2]
                    if row[2] is not None
                    else ""
                ).strip()

                grade = str(
                    row[3]
                    if row[3] is not None
                    else ""
                ).strip()

                section = str(
                    row[4]
                    if row[4] is not None
                    else ""
                ).strip().upper()

                if not student_id:
                    continue

                if not grade:
                    grade = "Other"

                if not section:
                    section = "-"

                group_key = (
                    grade,
                    section
                )

                if group_key not in grouped_students:
                    grouped_students[group_key] = []

                grouped_students[group_key].append(
                    (
                        student_id,
                        phone,
                        name,
                        grade,
                        section
                    )
                )

            if not grouped_students:
                self._add_empty_message()
                return

            # ======================================================
            # GRADE + SECTION GROUPS
            # ======================================================

            for grade, section in self._sort_groups(
                grouped_students.keys()
            ):

                self._add_grade_header(
                    grade,
                    section
                )

                students = sorted(
                    grouped_students[
                        (grade, section)
                    ],
                    key=lambda item: (
                        item[2].lower(),
                        item[0].lower()
                    )
                )

                for (
                    student_id,
                    phone,
                    name,
                    grade,
                    section
                ) in students:

                    self._add_student_button(
                        student_id,
                        phone,
                        name,
                        grade,
                        section
                    )

        except Exception as e:

            logging.error(
                f"Error loading student list: {e}"
            )

            self._show_status(
                "Unable to load students.",
                success=False
            )

    # ==============================================================
    # SORT GRADE + SECTION GROUPS
    # ==============================================================

    def _sort_groups(self, groups):
        """
        ترتيب المجموعات:

            Grade 1 A
            Grade 1 B
            Grade 2 A
            Grade 12 A

        وليس ترتيبًا أبجديًا فقط.
        """

        def group_key(group):

            grade, section = group

            try:
                grade_number = int(grade)
            except (ValueError, TypeError):
                grade_number = 9999

            return (
                grade_number,
                str(section).lower()
            )

        return sorted(
            groups,
            key=group_key
        )

    # ==============================================================
    # GRADE + SECTION HEADER
    # ==============================================================

    def _add_grade_header(
        self,
        grade,
        section
    ):

        header = Label(
            text=f"━━━ Grade {grade} {section} ━━━",
            size_hint_y=None,
            height=38,
            font_size="14sp",
            bold=True,
            color=(0, 1, 1, 1)
        )

        self.student_grid.add_widget(
            header
        )

    # ==============================================================
    # STUDENT BUTTON
    # ==============================================================

    def _add_student_button(
        self,
        student_id,
        phone,
        name,
        grade,
        section
    ):

        display_text = (
            f"ID: {student_id}   |   "
            f"{name}   |   "
            f"Phone: {phone}"
        )

        button = Button(
            text=display_text,
            size_hint_y=None,
            height=45,
            background_normal="",
            background_color=(
                0.1,
                0.14,
                0.22,
                1
            ),
            color=(
                1,
                0.85,
                0.6,
                1
            ),
            halign="left",
            valign="middle"
        )

        button.bind(
            size=lambda instance, value:
            setattr(
                instance,
                "text_size",
                (
                    instance.width - 20,
                    None
                )
            )
        )

        button.bind(
            on_press=lambda instance:
            self.select_student(
                student_id,
                phone,
                name,
                grade,
                section
            )
        )

        self.student_grid.add_widget(
            button
        )

    # ==============================================================
    # SELECT STUDENT
    # ==============================================================

    def select_student(
        self,
        student_id,
        phone,
        name,
        grade,
        section
    ):

        self.student_id_input.text = student_id
        self.name_input.text = name
        self.phone_input.text = phone
        self.grade_input.text = grade
        self.section_input.text = section

        self._show_status(
            f"Student {student_id} loaded for editing.",
            success=False,
            info=True
        )

    # ==============================================================
    # ADD STUDENT
    # ==============================================================

    def add_student(self, instance):

        if not self._is_admin_authenticated():
            self._go_to_login()
            return

        student_id = (
            self.student_id_input.text.strip()
        )

        phone = (
            self.phone_input.text.strip()
        )

        name = (
            self.name_input.text.strip()
        )

        grade = (
            self.grade_input.text.strip()
        )

        section = (
            self.section_input.text.strip().upper()
        )

        valid, message = self._validate_fields(
            student_id,
            phone,
            name,
            grade,
            section
        )

        if not valid:

            self._show_status(
                message,
                success=False
            )

            return

        try:

            from database.students import (
                add_student
            )

            success, message = add_student(
                student_id,
                phone,
                name,
                grade,
                section
            )

            if success:

                self._show_status(
                    message,
                    success=True
                )

                self.clear_fields()
                self.load_student_list()

            else:

                self._show_status(
                    message,
                    success=False
                )

        except Exception as e:

            logging.error(
                f"Add student screen error: {e}"
            )

            self._show_status(
                "Unable to add student.",
                success=False
            )

    # ==============================================================
    # UPDATE STUDENT
    # ==============================================================

    def update_student(self, instance):

        if not self._is_admin_authenticated():
            self._go_to_login()
            return

        student_id = (
            self.student_id_input.text.strip()
        )

        phone = (
            self.phone_input.text.strip()
        )

        name = (
            self.name_input.text.strip()
        )

        grade = (
            self.grade_input.text.strip()
        )

        section = (
            self.section_input.text.strip().upper()
        )

        valid, message = self._validate_fields(
            student_id,
            phone,
            name,
            grade,
            section
        )

        if not valid:

            self._show_status(
                message,
                success=False
            )

            return

        try:

            from database.students import (
                update_student
            )

            success, message = update_student(
                student_id,
                phone,
                name,
                grade,
                section
            )

            if success:

                self._show_status(
                    message,
                    success=True
                )

                self.clear_fields()
                self.load_student_list()

            else:

                self._show_status(
                    message,
                    success=False
                )

        except Exception as e:

            logging.error(
                f"Update student screen error: {e}"
            )

            self._show_status(
                "Unable to update student.",
                success=False
            )

    # ==============================================================
    # DELETE CONFIRMATION
    # ==============================================================

    def confirm_delete(self, instance):

        if not self._is_admin_authenticated():
            self._go_to_login()
            return

        student_id = (
            self.student_id_input.text.strip()
        )

        if not student_id:

            self._show_status(
                "Select a student before deleting.",
                success=False
            )

            return

        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=12
        )

        message = Label(
            text=(
                "Delete this student?\n\n"
                f"Student ID: {student_id}\n\n"
                "This action cannot be undone."
            ),
            halign="center",
            valign="middle"
        )

        message.bind(
            size=message.setter(
                "text_size"
            )
        )

        content.add_widget(
            message
        )

        buttons = BoxLayout(
            orientation="horizontal",
            spacing=10,
            size_hint_y=None,
            height=45
        )

        cancel_button = Button(
            text="Cancel",
            background_normal="",
            background_color=(
                0.5,
                0.5,
                0.5,
                1
            )
        )

        delete_button = Button(
            text="Delete",
            background_normal="",
            background_color=(
                0.75,
                0.2,
                0.2,
                1
            )
        )

        buttons.add_widget(
            cancel_button
        )

        buttons.add_widget(
            delete_button
        )

        content.add_widget(
            buttons
        )

        popup = Popup(
            title="Confirm Delete",
            content=content,
            size_hint=(0.85, 0.45),
            auto_dismiss=False
        )

        cancel_button.bind(
            on_press=popup.dismiss
        )

        delete_button.bind(
            on_press=lambda instance:
            self._delete_student(
                student_id,
                popup
            )
        )

        popup.open()

    # ==============================================================
    # DELETE STUDENT
    # ==============================================================

    def _delete_student(
        self,
        student_id,
        popup
    ):

        popup.dismiss()

        if not self._is_admin_authenticated():
            self._go_to_login()
            return

        try:

            from database.students import (
                delete_student
            )

            success, message = delete_student(
                student_id
            )

            if success:

                self._show_status(
                    message,
                    success=True
                )

                self.clear_fields()
                self.load_student_list()

            else:

                self._show_status(
                    message,
                    success=False
                )

        except Exception as e:

            logging.error(
                f"Delete student screen error: {e}"
            )

            self._show_status(
                "Unable to delete student.",
                success=False
            )

    # ==============================================================
    # VALIDATION
    # ==============================================================

    def _validate_fields(
        self,
        student_id,
        phone,
        name,
        grade,
        section
    ):

        if not student_id:

            return (
                False,
                "Student ID is required."
            )

        if not name:

            return (
                False,
                "Student name is required."
            )

        if not grade:

            return (
                False,
                "Grade is required."
            )

        if not grade.isdigit():

            return (
                False,
                "Grade must contain digits only."
            )

        grade_number = int(grade)

        if grade_number < 1 or grade_number > 12:

            return (
                False,
                "Grade must be between 1 and 12."
            )

        if not section:

            return (
                False,
                "Section is required."
            )

        if len(section) > 10:

            return (
                False,
                "Section is too long."
            )

        if not phone:

            return (
                False,
                "Guardian phone number is required."
            )

        if not phone.isdigit():

            return (
                False,
                "Phone number must contain digits only."
            )

        if len(phone) != 10:

            return (
                False,
                "Phone number must contain exactly 10 digits."
            )

        return True, ""

    # ==============================================================
    # CLEAR FIELDS
    # ==============================================================

    def clear_fields(self):

        self.student_id_input.text = ""
        self.name_input.text = ""
        self.grade_input.text = ""
        self.section_input.text = ""
        self.phone_input.text = ""

    # ==============================================================
    # CLEAR STATUS
    # ==============================================================

    def clear_status(self):

        self.status_label.text = ""

    # ==============================================================
    # STATUS
    # ==============================================================

    def _show_status(
        self,
        message,
        success=False,
        info=False
    ):

        self.status_label.text = str(
            message
        )

        if success:

            self.status_label.color = (
                0.2,
                0.8,
                0.4,
                1
            )

        elif info:

            self.status_label.color = (
                0.2,
                0.8,
                0.9,
                1
            )

        else:

            self.status_label.color = (
                0.9,
                0.3,
                0.3,
                1
            )

    # ==============================================================
    # EMPTY LIST
    # ==============================================================

    def _add_empty_message(self):

        label = Label(
            text="No students registered yet.",
            size_hint_y=None,
            height=50,
            color=(
                0.7,
                0.7,
                0.7,
                1
            )
        )

        self.student_grid.add_widget(
            label
        )

    # ==============================================================
    # BACK
    # ==============================================================

    def go_back(self, instance):

        self.clear_fields()
        self.clear_status()

        if self.manager:
            self.manager.current = "admin_reports"
