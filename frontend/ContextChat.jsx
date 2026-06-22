/**
 * ContextChat.jsx — wrapper React fino sobre o Web Component <context-chat>.
 *
 * Por que assim: o Web Component ja resolve tudo (estilo encapsulado, SSE,
 * ocultar no PDF). O React so precisa garantir que o script foi carregado e
 * renderizar a tag. Funciona em React/Vite e Next (adicione "use client").
 *
 *   import ContextChat from "./ContextChat";
 *   {isLastSlide && (
 *     <ContextChat endpoint="http://localhost:8000/api/v1/presentation/chat" title="Q&A" />
 *   )}
 *
 * Coloque context-chat.js em /public (Vite/Next servem estaticos de la) ou
 * passe a prop scriptSrc apontando para onde o arquivo esta acessivel.
 */
import { useEffect, useRef } from "react";

export default function ContextChat({
  endpoint = "http://localhost:8000/api/v1/presentation/chat",
  title = "Q&A com IA",
  auth = "",
  scriptSrc = "/context-chat.js",
}) {
  const ref = useRef(null);

  useEffect(() => {
    if (customElements.get("context-chat")) return;
    if (document.querySelector(`script[data-context-chat]`)) return;
    const s = document.createElement("script");
    s.src = scriptSrc;
    s.async = true;
    s.dataset.contextChat = "1";
    document.head.appendChild(s);
  }, [scriptSrc]);

  return <context-chat ref={ref} endpoint={endpoint} title={title} auth={auth} />;
}
