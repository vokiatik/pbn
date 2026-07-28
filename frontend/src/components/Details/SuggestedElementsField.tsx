import { Autocomplete, Box, Chip, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";

type SuggestedElementsFieldProps = {
    label: string;
    value: string[];
    suggestions: readonly string[];
    placeholder: string;
    disabled?: boolean;
    onChange: (value: string[]) => void;
};

export function SuggestedElementsField({
    label,
    value,
    suggestions,
    placeholder,
    disabled = false,
    onChange,
}: SuggestedElementsFieldProps) {
    const [inputValue, setInputValue] = useState("");
    const selectedKeys = new Set(value.map(valueKey));
    const availableSuggestions = suggestions.filter((suggestion) => !selectedKeys.has(valueKey(suggestion)));

    const commitInput = () => {
        if (!inputValue.trim()) return;
        onChange(normalizeElementValues([...value, inputValue]));
        setInputValue("");
    };

    return (
        <Stack spacing={1}>
            <Autocomplete<string, true, false, true>
                multiple
                freeSolo
                autoSelect
                clearOnBlur
                disabled={disabled}
                options={availableSuggestions}
                value={value}
                inputValue={inputValue}
                onInputChange={(_, nextValue, reason) => {
                    if (reason === "input" || reason === "clear") setInputValue(nextValue);
                }}
                onChange={(_, nextValue) => {
                    onChange(normalizeElementValues(nextValue));
                    setInputValue("");
                }}
                onKeyDown={(event) => {
                    if (event.key === "," && inputValue.trim()) {
                        event.preventDefault();
                        commitInput();
                    }
                }}
                renderTags={(selected, getTagProps) => selected.map((item, index) => {
                    const { key, ...tagProps } = getTagProps({ index });
                    return <Chip key={key} label={item} size="small" {...tagProps} />;
                })}
                renderInput={(params) => (
                    <TextField
                        {...params}
                        label={label}
                        size="small"
                        placeholder={value.length === 0 ? placeholder : undefined}
                        helperText="Type a custom item and press Enter, or choose a suggestion."
                    />
                )}
            />

            {availableSuggestions.length > 0 && (
                <Box>
                    <Typography variant="caption" color="text.secondary" display="block" mb={0.75}>
                        Suggestions for this category
                    </Typography>
                    <Stack direction="row" useFlexGap flexWrap="wrap" spacing={0.75}>
                        {availableSuggestions.map((suggestion) => (
                            <Chip
                                key={suggestion}
                                label={suggestion}
                                size="small"
                                variant="outlined"
                                disabled={disabled}
                                onClick={() => onChange(normalizeElementValues([...value, suggestion]))}
                            />
                        ))}
                    </Stack>
                </Box>
            )}
        </Stack>
    );
}

function normalizeElementValues(values: readonly string[]): string[] {
    const normalized: string[] = [];
    const seen = new Set<string>();

    for (const value of values) {
        for (const part of value.split(",")) {
            const trimmed = part.trim();
            const key = valueKey(trimmed);
            if (!trimmed || seen.has(key)) continue;
            seen.add(key);
            normalized.push(trimmed);
        }
    }

    return normalized;
}

function valueKey(value: string): string {
    return value.trim().toLowerCase();
}
