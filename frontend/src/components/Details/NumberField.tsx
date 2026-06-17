import { TextField } from "@mui/material";

type NumberFieldProps = {
    label: string;
    value: number;
    onChange: (value: number) => void;
    step?: number;
    min?: number;
    max?: number;
};

export function NumberField({
    label,
    value,
    onChange,
    step = 1,
    min,
    max,
}: NumberFieldProps) {
    return (
        <TextField
            label={label}
            type="number"
            size="small"
            value={value}
            inputProps={{ step, min, max }}
            onChange={(e) => onChange(Number(e.target.value))}
            fullWidth
        />
    );
}
