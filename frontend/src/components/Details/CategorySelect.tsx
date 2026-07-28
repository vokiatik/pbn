import { FormControl, FormHelperText, InputLabel, ListItemText, MenuItem, Select } from "@mui/material";
import type { AICategory } from "../../config/aiCategories";
import { AI_CATEGORY_OPTIONS, getAICategoryOption } from "../../config/aiCategories";

type CategorySelectProps = {
    value: AICategory;
    disabled?: boolean;
    onChange: (value: AICategory) => void;
};

export function CategorySelect({ value, disabled = false, onChange }: CategorySelectProps) {
    const selectedOption = getAICategoryOption(value);

    return (
        <FormControl fullWidth size="small" disabled={disabled}>
            <InputLabel>Category</InputLabel>
            <Select
                label="Category"
                value={value}
                renderValue={(selected) => getAICategoryOption(selected).label}
                onChange={(event) => onChange(event.target.value as AICategory)}
                MenuProps={{
                    PaperProps: {
                        sx: { maxWidth: 420 },
                    },
                }}
            >
                {AI_CATEGORY_OPTIONS.map((option) => (
                    <MenuItem key={option.value} value={option.value} sx={{ whiteSpace: "normal" }}>
                        <ListItemText
                            primary={option.label}
                            secondary={option.description}
                            secondaryTypographyProps={{ sx: { whiteSpace: "normal" } }}
                        />
                    </MenuItem>
                ))}
            </Select>
            <FormHelperText sx={{ mx: 0 }}>{selectedOption.description}</FormHelperText>
        </FormControl>
    );
}
