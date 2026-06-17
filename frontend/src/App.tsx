import { AppBar, Box, Button, Container, Toolbar, Typography } from "@mui/material";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { UploadPage } from "./pages/UploadPage";
import RequestsListPage from "./pages/RequestsListPage";
import { ProjectDetailsPage } from "./pages/ProjectDetailsPage";

export default function App() {
    return (
        <Box minHeight="100vh">
            <AppBar position="sticky" color="transparent" elevation={0} sx={{ backdropFilter: "blur(10px)" }}>
                <Toolbar>
                    <Typography variant="h6" sx={{ fontWeight: 700, flexGrow: 1 }}>
                        PBN Studio
                    </Typography>

                    <Button component={Link} to="/upload">
                        Upload
                    </Button>

                    <Button component={Link} to="/projects">
                        Projects
                    </Button>
                </Toolbar>
            </AppBar>

            <Container maxWidth="lg" sx={{ py: 4 }}>
                <Routes>
                    <Route path="/" element={<Navigate to="/upload" replace />} />
                    <Route path="/upload" element={<UploadPage />} />
                    <Route path="/projects" element={<RequestsListPage />} />
                    <Route path="/projects/:publicId" element={<ProjectDetailsPage />} />
                </Routes>
            </Container>
        </Box>
    );
}