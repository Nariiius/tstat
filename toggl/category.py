"""Category hierarchy: groups projects and assigns inherited colors."""

from dataclasses import dataclass, field


@dataclass
class Category:
    """A named group of projects with an inherited color."""
    name: str
    color: str
    projects: list[str] = field(default_factory=list)


class CategoryRegistry:
    """Maps project names to their parent Category for color inheritance.

    Loaded from the optional ``"categories"`` section of toggl_config.json.
    """

    def __init__(self, categories_config: dict | None = None):
        self._categories: list[Category] = []
        self._project_to_category: dict[str, Category] = {}
        if categories_config:
            for cat_name, cat_data in categories_config.items():
                color = cat_data.get("color", "")
                proj_list = cat_data.get("projects", [])
                cat = Category(name=cat_name, color=color, projects=list(proj_list))
                self._categories.append(cat)
                for proj in proj_list:
                    self._project_to_category[str(proj)] = cat

    def get_category(self, project_name: str) -> Category | None:
        """Return the parent Category for a project, or None if uncategorized."""
        return self._project_to_category.get(project_name)

    def get_color(self, project_name: str) -> str | None:
        """Return the inherited color for a project, or None."""
        cat = self._project_to_category.get(project_name)
        return cat.color if cat else None

    def update(self, other: "CategoryRegistry") -> None:
        """Replace contents in-place with a copy of another registry."""
        self._categories = list(other._categories)
        self._project_to_category = dict(other._project_to_category)

    def get_categories(self) -> list[Category]:
        """Return categories in config order."""
        return list(self._categories)

    def __len__(self):
        return len(self._categories)

    def __repr__(self):
        return f"CategoryRegistry({len(self._categories)} categories)"
